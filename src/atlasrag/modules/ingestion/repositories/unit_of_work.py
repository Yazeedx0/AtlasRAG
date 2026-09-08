from collections.abc import Callable
from datetime import datetime
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import ColumnElement

from atlasrag.contracts.ingestion import (
    IngestionLifecycleRepository,
    IngestionUnitOfWork as IngestionUnitOfWorkContract,
)
from atlasrag.contracts.jobs import JobOutboxRepository
from atlasrag.platform.jobs import OutboxRepository

from .ingestion import IngestionRepository


class IngestionUnitOfWork:
    ingestion: IngestionLifecycleRepository
    outbox: JobOutboxRepository

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        db_time: Callable[[], ColumnElement[datetime]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._db_time = db_time
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "IngestionUnitOfWork":
        self._session = self._session_factory()
        self.ingestion = IngestionRepository(self._session, db_time=self._db_time)
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
            raise RuntimeError("Ingestion unit of work is not active")

        try:
            if exc_type is not None or session.in_transaction():
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Ingestion unit of work is not active")
        await session.commit()


def make_ingestion_unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    db_time: Callable[[], ColumnElement[datetime]] | None = None,
) -> Callable[[], IngestionUnitOfWorkContract]:
    def factory() -> IngestionUnitOfWork:
        return IngestionUnitOfWork(session_factory, db_time=db_time)

    return factory


__all__ = ["IngestionUnitOfWork", "make_ingestion_unit_of_work_factory"]
