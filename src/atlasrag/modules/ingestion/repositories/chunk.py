from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.error.ingestion_errors import ChunkSetImmutable
from atlasrag.contracts.types.chunking import ChunkContentType, ChunkDraft
from atlasrag.contracts.types.ingestion import IngestionStatus
from atlasrag.modules.ingestion.models import Chunk, IngestionItem

COMPLETED_CHUNK_SET_IS_FROZEN = "ingestion item is completed"


class SqlAlchemyChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_item(
        self,
        *,
        ingestion_item_id: UUID,
        chunks: tuple[ChunkDraft, ...],
    ) -> None:
        await self._guard_mutable_chunk_set(ingestion_item_id=ingestion_item_id)
        await self._session.execute(
            delete(Chunk).where(Chunk.ingestion_item_id == ingestion_item_id)
        )
        if chunks:
            await self._session.execute(
                insert(Chunk),
                [
                    {
                        "ingestion_item_id": ingestion_item_id,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "content_type": chunk.content_type.value,
                        "section_title": chunk.section_title,
                        "section_path": list(chunk.section_path),
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "language_code": chunk.language_code,
                        "token_count": chunk.token_count,
                        "content_hash": chunk.content_hash,
                        "metadata": dict(chunk.metadata),
                    }
                    for chunk in chunks
                ],
            )
        return None

    async def list_for_item(self, *, ingestion_item_id: UUID) -> tuple[ChunkDraft, ...]:
        rows = (
            await self._session.execute(
                select(Chunk)
                .where(Chunk.ingestion_item_id == ingestion_item_id)
                .order_by(Chunk.chunk_index)
            )
        ).scalars()
        return tuple(
            ChunkDraft(
                chunk_index=row.chunk_index,
                content=row.content,
                content_type=ChunkContentType(row.content_type),
                section_title=row.section_title,
                section_path=tuple(row.section_path),
                page_start=row.page_start,
                page_end=row.page_end,
                language_code=row.language_code,
                token_count=row.token_count,
                content_hash=row.content_hash,
                metadata=row.chunk_metadata,
            )
            for row in rows
        )

    async def _guard_mutable_chunk_set(self, *, ingestion_item_id: UUID) -> None:
        # Embedding runs treat the chunk set of a completed item as immutable. The
        # owning row is locked so a concurrent completion cannot slip in between.
        status = (
            await self._session.execute(
                select(IngestionItem.status)
                .where(IngestionItem.id == ingestion_item_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if status is IngestionStatus.COMPLETED:
            raise ChunkSetImmutable(reason=COMPLETED_CHUNK_SET_IS_FROZEN)
        return None


__all__ = ["COMPLETED_CHUNK_SET_IS_FROZEN", "SqlAlchemyChunkRepository"]
