from collections.abc import Callable
from datetime import datetime
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import ColumnElement

from atlasrag.contracts.embedding import (
    ChunkEmbeddingRepository as ChunkEmbeddingRepositoryContract,
)
from atlasrag.contracts.embedding import (
    EmbeddingChunkSourceRepository,
)
from atlasrag.contracts.embedding import (
    EmbeddingModelRepository as EmbeddingModelRepositoryContract,
)
from atlasrag.contracts.embedding import (
    EmbeddingRunRepository as EmbeddingRunRepositoryContract,
)
from atlasrag.contracts.embedding import (
    EmbeddingUnitOfWork as EmbeddingUnitOfWorkContract,
)
from atlasrag.contracts.jobs import JobOutboxRepository
from atlasrag.platform.jobs import OutboxRepository

from .chunk_embedding import ChunkEmbeddingRepository
from .embedding_model import EmbeddingModelRepository
from .embedding_run import EmbeddingRunRepository

ChunkSourceFactory = Callable[[AsyncSession], EmbeddingChunkSourceRepository]


class EmbeddingUnitOfWork:
    models: EmbeddingModelRepositoryContract
    runs: EmbeddingRunRepositoryContract
    embeddings: ChunkEmbeddingRepositoryContract
    chunks: EmbeddingChunkSourceRepository
    outbox: JobOutboxRepository

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        chunk_source_factory: ChunkSourceFactory,
        db_time: Callable[[], ColumnElement[datetime]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._chunk_source_factory = chunk_source_factory
        self._db_time = db_time
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "EmbeddingUnitOfWork":
        self._session = self._session_factory()
        self.models = EmbeddingModelRepository(self._session)
        self.runs = EmbeddingRunRepository(self._session, db_time=self._db_time)
        self.embeddings = ChunkEmbeddingRepository(self._session)
        self.chunks = self._chunk_source_factory(self._session)
        self.outbox = OutboxRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Embedding unit of work is not active")

        try:
            if exc_type is not None or session.in_transaction():
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Embedding unit of work is not active")
        await session.commit()


def make_embedding_unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chunk_source_factory: ChunkSourceFactory,
    db_time: Callable[[], ColumnElement[datetime]] | None = None,
) -> Callable[[], EmbeddingUnitOfWorkContract]:
    def factory() -> EmbeddingUnitOfWork:
        return EmbeddingUnitOfWork(
            session_factory,
            chunk_source_factory=chunk_source_factory,
            db_time=db_time,
        )

    return factory


__all__ = [
    "ChunkSourceFactory",
    "EmbeddingUnitOfWork",
    "make_embedding_unit_of_work_factory",
]
