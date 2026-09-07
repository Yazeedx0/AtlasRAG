from typing import Protocol, runtime_checkable
from uuid import UUID

from atlasrag.contracts.types.chunking import ChunkDraft, ChunkState
from atlasrag.contracts.types.extraction import ExtractedDocument


@runtime_checkable
class TextTokenizer(Protocol):
    def count_tokens(self, text: str) -> int:
        ...

    def split_tokens(self, text: str) -> tuple[str, ...]:
        ...


@runtime_checkable
class Chunker(Protocol):
    def chunk(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None = None,
    ) -> tuple[ChunkDraft, ...]:
        ...


class ChunkRepository(Protocol):
    async def delete_for_item(self, *, ingestion_item_id: UUID) -> int:
        ...

    async def add_all(
        self,
        *,
        ingestion_item_id: UUID,
        drafts: tuple[ChunkDraft, ...],
    ) -> None:
        ...

    async def list_for_item(
        self,
        *,
        ingestion_item_id: UUID,
    ) -> tuple[ChunkState, ...]:
        ...

    async def count_for_item(self, *, ingestion_item_id: UUID) -> int:
        ...


__all__ = ["ChunkRepository", "Chunker", "TextTokenizer"]
