from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType

from atlasrag.contracts.types.extraction import (
    ExtractedBlockType,
    ExtractedDocument,
)

from evals.chunking.contract import (
    CHUNK_METADATA_SECTION_INDEX,
    CHUNK_METADATA_SPLIT_OF_BLOCK,
    ChunkingStrategy,
    EvalChunk,
)
from evals.core.tokenization import Tokenizer

FIXED_TOKEN_STRATEGY = "fixed-token"
HEADING_AWARE_STRATEGY = "heading-aware"
STRATEGY_VERSION = "1"

_DEFAULT_MAX_TOKENS = 256
_DEFAULT_OVERLAP_RATIO = 0.15
_DEFAULT_HEADING_LEVEL = 1


@dataclass(frozen=True, slots=True)
class FixedTokenConfig:
    max_tokens: int = _DEFAULT_MAX_TOKENS
    overlap_ratio: float = _DEFAULT_OVERLAP_RATIO


@dataclass(frozen=True, slots=True)
class HeadingAwareConfig:
    max_tokens: int = _DEFAULT_MAX_TOKENS
    repeat_heading: bool = True


@dataclass(frozen=True, slots=True)
class _Section:
    heading_path: tuple[str, ...]
    heading_index: int | None
    block_indexes: tuple[int, ...]


def _page_numbers(document: ExtractedDocument, indexes: Sequence[int]) -> tuple[int, ...]:
    pages = {
        document.blocks[index].page_number
        for index in indexes
        if document.blocks[index].page_number is not None
    }
    return tuple(sorted(page for page in pages if page is not None))


def _block_types(
    document: ExtractedDocument, indexes: Sequence[int]
) -> tuple[ExtractedBlockType, ...]:
    seen: list[ExtractedBlockType] = []
    for index in indexes:
        block_type = document.blocks[index].block_type
        if block_type not in seen:
            seen.append(block_type)
    return tuple(seen)


def _heading_level(document: ExtractedDocument, index: int) -> int:
    level = document.blocks[index].metadata.get("level", _DEFAULT_HEADING_LEVEL)
    return level if isinstance(level, int) else _DEFAULT_HEADING_LEVEL


def _build_sections(document: ExtractedDocument) -> tuple[_Section, ...]:
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []
    heading_path: tuple[str, ...] = ()
    heading_index: int | None = None
    body: list[int] = []

    def flush() -> None:
        sections.append(
            _Section(
                heading_path=heading_path,
                heading_index=heading_index,
                block_indexes=tuple(body),
            )
        )

    for index, block in enumerate(document.blocks):
        if block.block_type is not ExtractedBlockType.HEADING:
            body.append(index)
            continue
        if body or heading_index is not None:
            flush()
        level = _heading_level(document, index)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, block.text))
        heading_path = tuple(text for _, text in stack)
        heading_index = index
        body = []

    if body or heading_index is not None:
        flush()
    return tuple(sections)


class FixedTokenChunker:
    __slots__ = ("_config", "_tokenizer")

    def __init__(
        self, *, tokenizer: Tokenizer, config: FixedTokenConfig = FixedTokenConfig()
    ) -> None:
        self._tokenizer = tokenizer
        self._config = config

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy(
            name=FIXED_TOKEN_STRATEGY,
            version=STRATEGY_VERSION,
            configuration=MappingProxyType(
                {
                    "max_tokens": self._config.max_tokens,
                    "overlap_ratio": self._config.overlap_ratio,
                    "boundary": "token_window",
                    "structure_aware": False,
                }
            ),
        )

    def chunk(self, *, document: ExtractedDocument) -> tuple[EvalChunk, ...]:
        units: list[tuple[str, int]] = []
        for index, block in enumerate(document.blocks):
            for token in self._tokenizer.tokenize(block.text):
                units.append((token, index))
        if not units:
            return ()

        max_tokens = self._config.max_tokens
        step = max(1, max_tokens - round(max_tokens * self._config.overlap_ratio))
        chunks: list[EvalChunk] = []
        start = 0
        while start < len(units):
            window = units[start : start + max_tokens]
            indexes = sorted({index for _, index in window})
            chunks.append(
                EvalChunk(
                    ordinal=len(chunks),
                    text=self._tokenizer.detokenize([token for token, _ in window]),
                    heading_path=(),
                    page_numbers=_page_numbers(document, indexes),
                    block_types=_block_types(document, indexes),
                    source_block_indexes=tuple(indexes),
                    metadata=MappingProxyType({"window_start": start}),
                )
            )
            if start + max_tokens >= len(units):
                break
            start += step
        return tuple(chunks)


class HeadingAwareChunker:
    __slots__ = ("_config", "_tokenizer")

    def __init__(
        self, *, tokenizer: Tokenizer, config: HeadingAwareConfig = HeadingAwareConfig()
    ) -> None:
        self._tokenizer = tokenizer
        self._config = config

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy(
            name=HEADING_AWARE_STRATEGY,
            version=STRATEGY_VERSION,
            configuration=MappingProxyType(
                {
                    "max_tokens": self._config.max_tokens,
                    "repeat_heading": self._config.repeat_heading,
                    "boundary": "heading_then_block",
                    "structure_aware": True,
                }
            ),
        )

    def chunk(self, *, document: ExtractedDocument) -> tuple[EvalChunk, ...]:
        chunks: list[EvalChunk] = []
        for section_index, section in enumerate(_build_sections(document)):
            if not section.block_indexes:
                continue
            self._emit_section(
                document=document,
                section=section,
                section_index=section_index,
                chunks=chunks,
            )
        return tuple(chunks)

    def _heading_prefix(self, document: ExtractedDocument, section: _Section) -> str:
        if section.heading_index is None or not self._config.repeat_heading:
            return ""
        return document.blocks[section.heading_index].text

    def _emit_section(
        self,
        *,
        document: ExtractedDocument,
        section: _Section,
        section_index: int,
        chunks: list[EvalChunk],
    ) -> None:
        prefix = self._heading_prefix(document, section)
        prefix_tokens = self._tokenizer.count(prefix) if prefix else 0
        budget = max(1, self._config.max_tokens - prefix_tokens)

        pending: list[int] = []
        pending_tokens = 0

        def flush() -> None:
            nonlocal pending, pending_tokens
            if not pending:
                return
            chunks.append(
                self._build_chunk(
                    document=document,
                    section=section,
                    section_index=section_index,
                    prefix=prefix,
                    block_indexes=tuple(pending),
                    ordinal=len(chunks),
                    split_of_block=None,
                    body_text=None,
                )
            )
            pending = []
            pending_tokens = 0

        for index in section.block_indexes:
            block_tokens = self._tokenizer.count(document.blocks[index].text)
            if block_tokens > budget:
                flush()
                self._emit_split_block(
                    document=document,
                    section=section,
                    section_index=section_index,
                    prefix=prefix,
                    block_index=index,
                    budget=budget,
                    chunks=chunks,
                )
                continue
            if pending and pending_tokens + block_tokens > budget:
                flush()
            pending.append(index)
            pending_tokens += block_tokens
        flush()

    def _emit_split_block(
        self,
        *,
        document: ExtractedDocument,
        section: _Section,
        section_index: int,
        prefix: str,
        block_index: int,
        budget: int,
        chunks: list[EvalChunk],
    ) -> None:
        tokens = self._tokenizer.tokenize(document.blocks[block_index].text)
        for start in range(0, len(tokens), budget):
            window = tokens[start : start + budget]
            chunks.append(
                self._build_chunk(
                    document=document,
                    section=section,
                    section_index=section_index,
                    prefix=prefix,
                    block_indexes=(block_index,),
                    ordinal=len(chunks),
                    split_of_block=block_index,
                    body_text=self._tokenizer.detokenize(window),
                )
            )

    def _build_chunk(
        self,
        *,
        document: ExtractedDocument,
        section: _Section,
        section_index: int,
        prefix: str,
        block_indexes: tuple[int, ...],
        ordinal: int,
        split_of_block: int | None,
        body_text: str | None,
    ) -> EvalChunk:
        body = (
            body_text
            if body_text is not None
            else "\n\n".join(document.blocks[index].text for index in block_indexes)
        )
        text = f"{prefix}\n\n{body}" if prefix else body
        provenance_indexes = block_indexes
        if section.heading_index is not None:
            provenance_indexes = (section.heading_index, *block_indexes)
        metadata: dict[str, object] = {CHUNK_METADATA_SECTION_INDEX: section_index}
        if split_of_block is not None:
            metadata[CHUNK_METADATA_SPLIT_OF_BLOCK] = split_of_block
        return EvalChunk(
            ordinal=ordinal,
            text=text,
            heading_path=section.heading_path,
            page_numbers=_page_numbers(document, provenance_indexes),
            block_types=_block_types(document, block_indexes),
            source_block_indexes=provenance_indexes,
            metadata=MappingProxyType(metadata),
        )


__all__ = [
    "FIXED_TOKEN_STRATEGY",
    "HEADING_AWARE_STRATEGY",
    "STRATEGY_VERSION",
    "FixedTokenChunker",
    "FixedTokenConfig",
    "HeadingAwareChunker",
    "HeadingAwareConfig",
]
