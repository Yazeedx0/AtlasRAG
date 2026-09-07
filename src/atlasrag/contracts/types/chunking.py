import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})


class ChunkContentType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    CODE = "code"
    OTHER = "other"


class ChunkingStrategy(StrEnum):
    FIXED_TOKEN_V1 = "fixed_token_v1"  # noqa: S105
    HEADING_AWARE_V1 = "heading_aware_v1"


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    chunk_index: int
    content: str
    content_type: ChunkContentType
    token_count: int
    content_hash: str
    section_title: str | None = None
    section_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    language_code: str | None = None
    metadata: Mapping[str, object] = _EMPTY_METADATA


@dataclass(frozen=True, slots=True)
class ChunkState:
    id: uuid.UUID
    ingestion_item_id: uuid.UUID
    parent_chunk_id: uuid.UUID | None
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
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None


__all__ = [
    "ChunkContentType",
    "ChunkDraft",
    "ChunkState",
    "ChunkingStrategy",
]
