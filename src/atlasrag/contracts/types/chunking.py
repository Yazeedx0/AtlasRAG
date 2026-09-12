from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})


class ChunkContentType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    CODE = "code"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    chunk_index: int
    content: str
    content_type: ChunkContentType

    section_title: str | None
    section_path: tuple[str, ...]

    page_start: int | None
    page_end: int | None

    language_code: str | None

    token_count: int
    content_hash: str

    metadata: Mapping[str, object] = _EMPTY_METADATA


__all__ = [
    "ChunkContentType",
    "ChunkDraft",
]
