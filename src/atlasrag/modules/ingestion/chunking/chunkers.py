from collections.abc import Iterable

from atlasrag.contracts.chunking import ReferenceTokenizer
from atlasrag.contracts.types.chunking import ChunkContentType, ChunkDraft
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
)

from .config import ChunkingConfig
from .hashing import normalized_content_hash


class FixedTokenChunker:
    def __init__(self, *, tokenizer: ReferenceTokenizer, config: ChunkingConfig) -> None:
        self._tokenizer = tokenizer
        self._config = config

    def chunk(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None = None,
    ) -> tuple[ChunkDraft, ...]:
        blocks = tuple(block for block in document.blocks if block.text.strip())
        if not blocks:
            return ()
        content = "\n\n".join(block.text.strip() for block in blocks)
        builder = _DraftBuilder(tokenizer=self._tokenizer, language_code=language_code)
        for piece in self._tokenizer.split(
            text=content,
            max_tokens=self._config.max_tokens,
            overlap_tokens=self._config.overlap_tokens,
        ):
            builder.add(
                content=piece,
                blocks=blocks,
                section_title=None,
                section_path=(),
                content_type=_content_type(blocks),
            )
        return builder.build()


class HeadingAwareChunker:
    def __init__(self, *, tokenizer: ReferenceTokenizer, config: ChunkingConfig) -> None:
        self._tokenizer = tokenizer
        self._config = config

    def chunk(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None = None,
    ) -> tuple[ChunkDraft, ...]:
        builder = _DraftBuilder(tokenizer=self._tokenizer, language_code=language_code)
        section_blocks: list[ExtractedBlock] = []
        section_title: str | None = None
        section_path: tuple[str, ...] = ()

        for block in document.blocks:
            if block.block_type is ExtractedBlockType.HEADING:
                self._emit_section(
                    builder=builder,
                    blocks=tuple(section_blocks),
                    section_title=section_title,
                    section_path=section_path,
                )
                section_blocks = []
                section_title = block.text.strip() or None
                section_path = (section_title,) if section_title is not None else ()
            elif block.text.strip():
                section_blocks.append(block)

        self._emit_section(
            builder=builder,
            blocks=tuple(section_blocks),
            section_title=section_title,
            section_path=section_path,
        )
        return builder.build()

    def _emit_section(
        self,
        *,
        builder: "_DraftBuilder",
        blocks: tuple[ExtractedBlock, ...],
        section_title: str | None,
        section_path: tuple[str, ...],
    ) -> None:
        if not blocks:
            return
        content = "\n\n".join(block.text.strip() for block in blocks)
        if self._tokenizer.count(text=content) <= self._config.max_tokens:
            builder.add(
                content=content,
                blocks=blocks,
                section_title=section_title,
                section_path=section_path,
                content_type=_content_type(blocks),
            )
            return

        pending: list[ExtractedBlock] = []
        for block in blocks:
            if self._config.preserve_tables and block.block_type is ExtractedBlockType.TABLE:
                self._emit_text_blocks(
                    builder=builder,
                    blocks=tuple(pending),
                    section_title=section_title,
                    section_path=section_path,
                )
                pending = []
                self._emit_table(
                    builder=builder,
                    block=block,
                    section_title=section_title,
                    section_path=section_path,
                )
            else:
                pending.append(block)
        self._emit_text_blocks(
            builder=builder,
            blocks=tuple(pending),
            section_title=section_title,
            section_path=section_path,
        )

    def _emit_text_blocks(
        self,
        *,
        builder: "_DraftBuilder",
        blocks: tuple[ExtractedBlock, ...],
        section_title: str | None,
        section_path: tuple[str, ...],
    ) -> None:
        if not blocks:
            return
        content = "\n\n".join(block.text.strip() for block in blocks)
        for piece in self._tokenizer.split(
            text=content,
            max_tokens=self._config.max_tokens,
            overlap_tokens=self._config.overlap_tokens,
        ):
            builder.add(
                content=piece,
                blocks=blocks,
                section_title=section_title,
                section_path=section_path,
                content_type=_content_type(blocks),
            )

    def _emit_table(
        self,
        *,
        builder: "_DraftBuilder",
        block: ExtractedBlock,
        section_title: str | None,
        section_path: tuple[str, ...],
    ) -> None:
        lines = tuple(line.rstrip() for line in block.text.splitlines() if line.strip())
        if len(lines) < 3 or not _is_markdown_table(lines):
            self._emit_text_blocks(
                builder=builder,
                blocks=(block,),
                section_title=section_title,
                section_path=section_path,
            )
            return

        header = lines[:2]
        rows = lines[2:]
        current_rows: list[str] = []
        for row in rows:
            candidate = "\n".join((*header, *current_rows, row))
            if not current_rows and self._tokenizer.count(text=candidate) > self._config.max_tokens:
                for piece in self._tokenizer.split(
                    text=candidate,
                    max_tokens=self._config.max_tokens,
                    overlap_tokens=0,
                ):
                    builder.add(
                        content=piece,
                        blocks=(block,),
                        section_title=section_title,
                        section_path=section_path,
                        content_type=ChunkContentType.TABLE,
                    )
                continue
            if current_rows and self._tokenizer.count(text=candidate) > self._config.max_tokens:
                builder.add(
                    content="\n".join((*header, *current_rows)),
                    blocks=(block,),
                    section_title=section_title,
                    section_path=section_path,
                    content_type=ChunkContentType.TABLE,
                )
                current_rows = [row]
            else:
                current_rows.append(row)
        if current_rows:
            builder.add(
                content="\n".join((*header, *current_rows)),
                blocks=(block,),
                section_title=section_title,
                section_path=section_path,
                content_type=ChunkContentType.TABLE,
            )


class _DraftBuilder:
    def __init__(self, *, tokenizer: ReferenceTokenizer, language_code: str | None) -> None:
        self._tokenizer = tokenizer
        self._language_code = language_code
        self._drafts: list[ChunkDraft] = []

    def add(
        self,
        *,
        content: str,
        blocks: Iterable[ExtractedBlock],
        section_title: str | None,
        section_path: tuple[str, ...],
        content_type: ChunkContentType,
    ) -> None:
        clean_content = content.strip()
        if not clean_content:
            return
        block_tuple = tuple(blocks)
        pages = tuple(block.page_number for block in block_tuple if block.page_number is not None)
        self._drafts.append(
            ChunkDraft(
                chunk_index=len(self._drafts),
                content=clean_content,
                content_type=content_type,
                section_title=section_title,
                section_path=section_path,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                language_code=self._language_code,
                token_count=self._tokenizer.count(text=clean_content),
                content_hash=normalized_content_hash(clean_content),
            )
        )

    def build(self) -> tuple[ChunkDraft, ...]:
        return tuple(self._drafts)


def _content_type(blocks: Iterable[ExtractedBlock]) -> ChunkContentType:
    types = {block.block_type for block in blocks}
    if types == {ExtractedBlockType.TABLE}:
        return ChunkContentType.TABLE
    if types == {ExtractedBlockType.CODE}:
        return ChunkContentType.CODE
    if ExtractedBlockType.TABLE in types or ExtractedBlockType.CODE in types:
        return ChunkContentType.MIXED
    return ChunkContentType.TEXT


def _is_markdown_table(lines: tuple[str, ...]) -> bool:
    return "|" in lines[0] and "-" in lines[1] and "|" in lines[1]


__all__ = ["FixedTokenChunker", "HeadingAwareChunker"]
