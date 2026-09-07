from collections.abc import Callable
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.contracts.jobs import (
    JobOutboxRepository,
    JobOutboxUnitOfWork as JobOutboxUnitOfWorkContract,
)
from atlasrag.platform.jobs.repositories import OutboxRepository


class JobOutboxUnitOfWork:
    outbox: JobOutboxRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "JobOutboxUnitOfWork":
        self._session = self._session_factory()
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
            raise RuntimeError("Job outbox unit of work is not active")

        try:
            if exc_type is not None or session.in_transaction():
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Job outbox unit of work is not active")
        await session.commit()


def make_job_outbox_unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], JobOutboxUnitOfWorkContract]:
    def factory() -> JobOutboxUnitOfWork:
        return JobOutboxUnitOfWork(session_factory)

    return factory


__all__ = ["JobOutboxUnitOfWork", "make_job_outbox_unit_of_work_factory"]
