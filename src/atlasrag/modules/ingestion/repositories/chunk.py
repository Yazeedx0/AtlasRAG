from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types.chunking import ChunkDraft, ChunkState
from atlasrag.modules.ingestion.models import Chunk

CHUNK_INDEX_CONSTRAINT = "uq_chunks_item_chunk_index"


def _chunk_columns() -> tuple[object, ...]:
    return (
        Chunk.id,
        Chunk.ingestion_item_id,
        Chunk.parent_chunk_id,
        Chunk.chunk_index,
        Chunk.content,
        Chunk.content_type,
        Chunk.section_title,
        Chunk.section_path,
        Chunk.page_start,
        Chunk.page_end,
        Chunk.language_code,
        Chunk.token_count,
        Chunk.content_hash,
        Chunk.metadata_,
        Chunk.created_at,
    )


def _to_chunk_state(row: Row) -> ChunkState:
    return ChunkState(
        id=row.id,
        ingestion_item_id=row.ingestion_item_id,
        parent_chunk_id=row.parent_chunk_id,
        chunk_index=row.chunk_index,
        content=row.content,
        content_type=row.content_type,
        section_title=row.section_title,
        section_path=tuple(row.section_path),
        page_start=row.page_start,
        page_end=row.page_end,
        language_code=row.language_code,
        token_count=row.token_count,
        content_hash=row.content_hash,
        metadata=row.metadata_,
        created_at=row.created_at,
    )


def _to_values(*, ingestion_item_id: UUID, draft: ChunkDraft) -> dict[str, object]:
    return {
        "id": uuid4(),
        "ingestion_item_id": ingestion_item_id,
        "parent_chunk_id": None,
        "chunk_index": draft.chunk_index,
        "content": draft.content,
        "content_type": draft.content_type,
        "section_title": draft.section_title,
        "section_path": list(draft.section_path),
        "page_start": draft.page_start,
        "page_end": draft.page_end,
        "language_code": draft.language_code,
        "token_count": draft.token_count,
        "content_hash": draft.content_hash,
        "metadata_": dict(draft.metadata),
    }


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def delete_for_item(self, *, ingestion_item_id: UUID) -> int:
        statement = delete(Chunk).where(Chunk.ingestion_item_id == ingestion_item_id)
        result = await self._session.execute(statement)
        return result.rowcount

    async def add_all(
        self,
        *,
        ingestion_item_id: UUID,
        drafts: tuple[ChunkDraft, ...],
    ) -> None:
        if not drafts:
            return None

        await self._session.execute(
            insert(Chunk),
            [
                _to_values(ingestion_item_id=ingestion_item_id, draft=draft)
                for draft in drafts
            ],
        )
        return None

    async def list_for_item(
        self,
        *,
        ingestion_item_id: UUID,
    ) -> tuple[ChunkState, ...]:
        statement = (
            select(*_chunk_columns())
            .where(Chunk.ingestion_item_id == ingestion_item_id)
            .order_by(Chunk.chunk_index)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(_to_chunk_state(row) for row in rows)

    async def count_for_item(self, *, ingestion_item_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.ingestion_item_id == ingestion_item_id)
        )
        return (await self._session.execute(statement)).scalar_one()


__all__ = ["CHUNK_INDEX_CONSTRAINT", "ChunkRepository"]
