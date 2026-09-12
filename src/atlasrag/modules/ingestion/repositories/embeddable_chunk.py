from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types.embedding import EmbeddableChunk
from atlasrag.contracts.types.ingestion import IngestionStatus
from atlasrag.modules.ingestion.models import Chunk, IngestionItem


class EmbeddableChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_item_embeddable(self, *, ingestion_item_id: UUID) -> bool:
        status = (
            await self._session.execute(
                select(IngestionItem.status).where(IngestionItem.id == ingestion_item_id)
            )
        ).scalar_one_or_none()
        return status is IngestionStatus.COMPLETED

    async def list_chunks(self, *, ingestion_item_id: UUID) -> tuple[EmbeddableChunk, ...]:
        rows = (
            await self._session.execute(
                select(Chunk.id, Chunk.chunk_index, Chunk.content, Chunk.token_count)
                .where(Chunk.ingestion_item_id == ingestion_item_id)
                .order_by(Chunk.chunk_index)
            )
        ).all()
        return tuple(
            EmbeddableChunk(
                chunk_id=row.id,
                chunk_index=row.chunk_index,
                content=row.content,
                token_count=row.token_count,
            )
            for row in rows
        )

    async def list_chunk_ids(self, *, ingestion_item_id: UUID) -> tuple[UUID, ...]:
        rows = (
            await self._session.execute(
                select(Chunk.id)
                .where(Chunk.ingestion_item_id == ingestion_item_id)
                .order_by(Chunk.chunk_index)
            )
        ).scalars()
        return tuple(rows)


__all__ = ["EmbeddableChunkRepository"]
