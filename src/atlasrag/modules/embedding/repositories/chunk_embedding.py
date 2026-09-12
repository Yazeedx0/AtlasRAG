import uuid

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types.embedding import ChunkVector
from atlasrag.modules.embedding.models import ChunkEmbedding


class ChunkEmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_model(
        self,
        *,
        embedding_model_id: uuid.UUID,
        embedding_run_id: uuid.UUID,
        dimension: int,
        chunk_ids: tuple[uuid.UUID, ...],
        vectors: tuple[ChunkVector, ...],
    ) -> None:
        if chunk_ids:
            await self._session.execute(
                delete(ChunkEmbedding).where(
                    ChunkEmbedding.embedding_model_id == embedding_model_id,
                    ChunkEmbedding.chunk_id.in_(chunk_ids),
                )
            )
        if vectors:
            await self._session.execute(
                insert(ChunkEmbedding),
                [
                    {
                        "chunk_id": vector.chunk_id,
                        "embedding_model_id": embedding_model_id,
                        "embedding_run_id": embedding_run_id,
                        "dimension": dimension,
                        "embedding": list(vector.values),
                    }
                    for vector in vectors
                ],
            )
        return None

    async def count_for_model(
        self,
        *,
        embedding_model_id: uuid.UUID,
        chunk_ids: tuple[uuid.UUID, ...],
    ) -> int:
        if not chunk_ids:
            return 0
        statement = select(func.count()).where(
            ChunkEmbedding.embedding_model_id == embedding_model_id,
            ChunkEmbedding.chunk_id.in_(chunk_ids),
        )
        return (await self._session.execute(statement)).scalar_one()


__all__ = ["ChunkEmbeddingRepository"]
