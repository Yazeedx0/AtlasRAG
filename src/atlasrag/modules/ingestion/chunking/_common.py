import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from atlasrag.contracts.chunking import TextTokenizer
from atlasrag.contracts.types.chunking import ChunkContentType, ChunkDraft
from atlasrag.contracts.types.extraction import ExtractedBlock, ExtractedBlockType

_HASH_FIELD_SEPARATOR = "\x1f"
_HASH_PATH_SEPARATOR = "\x1e"

_BLOCK_CONTENT_TYPES: dict[ExtractedBlockType, ChunkContentType] = {
    ExtractedBlockType.TABLE: ChunkContentType.TABLE,
    ExtractedBlockType.CODE: ChunkContentType.CODE,
    ExtractedBlockType.HEADING: ChunkContentType.TEXT,
    ExtractedBlockType.PARAGRAPH: ChunkContentType.TEXT,
    ExtractedBlockType.LIST: ChunkContentType.TEXT,
    ExtractedBlockType.OTHER: ChunkContentType.OTHER,
}


@dataclass(frozen=True, slots=True)
class ChunkPiece:
    content: str
    content_type: ChunkContentType
    section_title: str | None = None
    section_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


def content_type_for_block(block_type: ExtractedBlockType) -> ChunkContentType:
    return _BLOCK_CONTENT_TYPES.get(block_type, ChunkContentType.OTHER)


def compute_content_hash(
    *,
    content: str,
    content_type: ChunkContentType,
    section_path: Sequence[str],
) -> str:
    payload = _HASH_FIELD_SEPARATOR.join(
        (
            content_type.value,
            _HASH_PATH_SEPARATOR.join(section_path),
            content,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def token_windows(
    token_count: int,
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> Iterator[tuple[int, int]]:
    step = max_tokens - overlap_tokens
    start = 0
    while start < token_count:
        end = min(start + max_tokens, token_count)
        yield start, end
        if end == token_count:
            return
        start += step


def page_range(pages: Sequence[int | None]) -> tuple[int | None, int | None]:
    known = [page for page in pages if page is not None]
    if not known:
        return None, None
    return min(known), max(known)


def block_page_range(
    blocks: Sequence[ExtractedBlock],
) -> tuple[int | None, int | None]:
    return page_range([block.page_number for block in blocks])


def validate_token_bounds(*, max_tokens: int, overlap_tokens: int) -> None:
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must not be negative")
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")


def finalize_pieces(
    pieces: Sequence[ChunkPiece],
    *,
    tokenizer: TextTokenizer,
    language_code: str | None,
) -> tuple[ChunkDraft, ...]:
    drafts: list[ChunkDraft] = []
    for piece in pieces:
        content = piece.content.strip()
        if not content:
            continue
        drafts.append(
            ChunkDraft(
                chunk_index=len(drafts),
                content=content,
                content_type=piece.content_type,
                token_count=tokenizer.count_tokens(content),
                content_hash=compute_content_hash(
                    content=content,
                    content_type=piece.content_type,
                    section_path=piece.section_path,
                ),
                section_title=piece.section_title,
                section_path=piece.section_path,
                page_start=piece.page_start,
                page_end=piece.page_end,
                language_code=language_code,
                metadata=dict(piece.metadata),
            )
        )
    return tuple(drafts)


__all__ = [
    "ChunkPiece",
    "block_page_range",
    "compute_content_hash",
    "content_type_for_block",
    "finalize_pieces",
    "page_range",
    "token_windows",
    "validate_token_bounds",
]
