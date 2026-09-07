from dataclasses import dataclass

from atlasrag.contracts.chunking import TextTokenizer
from atlasrag.contracts.types.chunking import (
    ChunkContentType,
    ChunkDraft,
    ChunkingStrategy,
)
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
)

from ._common import (
    ChunkPiece,
    finalize_pieces,
    page_range,
    token_windows,
    validate_token_bounds,
)
from ._tables import split_table
from .tokenizer import ReferenceTextTokenizer

DEFAULT_MAX_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 64
MAX_HEADING_LEVEL = 9

_STRATEGY = ChunkingStrategy.HEADING_AWARE_V1.value
_PARAGRAPH_SEPARATOR = "\n\n"
_HEADING_MARKER = "#"
_HEADING_LEVEL_KEYS = ("level", "heading_level")


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    token_count: int
    page_number: int | None


@dataclass(frozen=True, slots=True)
class _Group:
    blocks: tuple[ExtractedBlock, ...]
    content_type: ChunkContentType
    section_path: tuple[str, ...]


class HeadingAwareChunker:
    def __init__(
        self,
        *,
        tokenizer: TextTokenizer | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    ) -> None:
        validate_token_bounds(max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        self._tokenizer = tokenizer or ReferenceTextTokenizer()
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

    def chunk(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None = None,
    ) -> tuple[ChunkDraft, ...]:
        pieces: list[ChunkPiece] = []
        for group in self._group_blocks(document):
            if group.content_type is ChunkContentType.TABLE:
                pieces.extend(self._pack_table(group))
            else:
                pieces.extend(self._pack_flow(group))
        return finalize_pieces(
            pieces,
            tokenizer=self._tokenizer,
            language_code=language_code,
        )

    def _group_blocks(self, document: ExtractedDocument) -> list[_Group]:
        groups: list[_Group] = []
        headings: list[tuple[int, str]] = []
        pending: list[ExtractedBlock] = []
        pending_type = ChunkContentType.TEXT
        pending_path: tuple[str, ...] = ()

        def flush() -> None:
            nonlocal pending
            if pending:
                groups.append(
                    _Group(
                        blocks=tuple(pending),
                        content_type=pending_type,
                        section_path=pending_path,
                    )
                )
                pending = []

        for block in document.blocks:
            if not block.text.strip():
                continue

            if block.block_type is ExtractedBlockType.HEADING:
                flush()
                level = _heading_level(block)
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, _heading_title(block)))
                continue

            section_path = tuple(title for _, title in headings)
            content_type = _flow_content_type(block.block_type)

            if content_type is ChunkContentType.TABLE:
                flush()
                groups.append(
                    _Group(
                        blocks=(block,),
                        content_type=content_type,
                        section_path=section_path,
                    )
                )
                continue

            if pending and pending_type is not content_type:
                flush()

            pending_type = content_type
            pending_path = section_path
            pending.append(block)

        flush()
        return groups

    def _pack_flow(self, group: _Group) -> list[ChunkPiece]:
        units = self._flow_units(group.blocks)
        if not units:
            return []

        parts = self._pack_units(units)
        pieces: list[ChunkPiece] = []
        previous_body: str | None = None
        for index, part in enumerate(parts):
            body = _PARAGRAPH_SEPARATOR.join(unit.text for unit in part)
            content = (
                body
                if previous_body is None
                else self._with_overlap(body=body, previous_body=previous_body)
            )
            previous_body = body
            page_start, page_end = page_range([unit.page_number for unit in part])
            pieces.append(
                ChunkPiece(
                    content=content,
                    content_type=group.content_type,
                    section_title=_section_title(group.section_path),
                    section_path=group.section_path,
                    page_start=page_start,
                    page_end=page_end,
                    metadata=_part_metadata(index=index, total=len(parts)),
                )
            )
        return pieces

    def _pack_table(self, group: _Group) -> list[ChunkPiece]:
        block = group.blocks[0]
        parts = split_table(
            block.text.strip(),
            tokenizer=self._tokenizer,
            max_tokens=self._max_tokens,
            overlap_tokens=self._overlap_tokens,
        )
        pieces: list[ChunkPiece] = []
        for index, part in enumerate(parts):
            metadata = _part_metadata(index=index, total=len(parts))
            if len(parts) > 1:
                metadata["table_header_repeated"] = part.header_repeated
            pieces.append(
                ChunkPiece(
                    content=part.content,
                    content_type=ChunkContentType.TABLE,
                    section_title=_section_title(group.section_path),
                    section_path=group.section_path,
                    page_start=block.page_number,
                    page_end=block.page_number,
                    metadata=metadata,
                )
            )
        return pieces

    def _flow_units(self, blocks: tuple[ExtractedBlock, ...]) -> list[_Unit]:
        units: list[_Unit] = []
        for block in blocks:
            text = block.text.strip()
            token_count = self._tokenizer.count_tokens(text)
            if token_count == 0:
                continue

            if token_count <= self._max_tokens:
                units.append(
                    _Unit(
                        text=text,
                        token_count=token_count,
                        page_number=block.page_number,
                    )
                )
                continue

            segments = self._tokenizer.split_tokens(text)
            for start, end in token_windows(
                len(segments),
                max_tokens=self._max_tokens,
                overlap_tokens=self._overlap_tokens,
            ):
                window = "".join(segments[start:end]).strip()
                units.append(
                    _Unit(
                        text=window,
                        token_count=self._tokenizer.count_tokens(window),
                        page_number=block.page_number,
                    )
                )
        return units

    def _pack_units(self, units: list[_Unit]) -> list[list[_Unit]]:
        parts: list[list[_Unit]] = []
        current: list[_Unit] = []
        current_tokens = 0

        for unit in units:
            budget = self._max_tokens - (self._overlap_tokens if parts else 0)
            if current and current_tokens + unit.token_count > budget:
                parts.append(current)
                current = []
                current_tokens = 0
            current.append(unit)
            current_tokens += unit.token_count

        if current:
            parts.append(current)
        return parts

    def _with_overlap(self, *, body: str, previous_body: str) -> str:
        allowance = self._max_tokens - self._tokenizer.count_tokens(body)
        take = min(self._overlap_tokens, max(allowance, 0))
        if take < 1:
            return body

        segments = self._tokenizer.split_tokens(previous_body)
        overlap = "".join(segments[-take:]).strip()
        return f"{overlap}{_PARAGRAPH_SEPARATOR}{body}" if overlap else body


def _part_metadata(*, index: int, total: int) -> dict[str, object]:
    metadata: dict[str, object] = {"strategy": _STRATEGY}
    if total > 1:
        metadata["part"] = index + 1
        metadata["parts"] = total
    return metadata


def _section_title(section_path: tuple[str, ...]) -> str | None:
    return section_path[-1] if section_path else None


def _flow_content_type(block_type: ExtractedBlockType) -> ChunkContentType:
    if block_type is ExtractedBlockType.TABLE:
        return ChunkContentType.TABLE
    if block_type is ExtractedBlockType.CODE:
        return ChunkContentType.CODE
    return ChunkContentType.TEXT


def _heading_level(block: ExtractedBlock) -> int:
    for key in _HEADING_LEVEL_KEYS:
        value = block.metadata.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            continue
        if 1 <= value <= MAX_HEADING_LEVEL:
            return value

    marker_count = len(block.text.strip()) - len(block.text.strip().lstrip(_HEADING_MARKER))
    return marker_count if 1 <= marker_count <= MAX_HEADING_LEVEL else 1


def _heading_title(block: ExtractedBlock) -> str:
    text = block.text.strip()
    stripped = text.lstrip(_HEADING_MARKER).strip()
    return stripped or text


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_OVERLAP_TOKENS",
    "MAX_HEADING_LEVEL",
    "HeadingAwareChunker",
]
