from collections.abc import Callable
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.contracts.identity import IdentityRepository
from atlasrag.platform.database.identity.repository import SqlAlchemyIdentityRepository


class SqlAlchemyIdentityUnitOfWork:
    identities: IdentityRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "SqlAlchemyIdentityUnitOfWork":
        self._session = self._session_factory()
        self.identities = SqlAlchemyIdentityRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Identity unit of work is not active")

        try:
            if exc_type is not None or session.in_transaction():
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Identity unit of work is not active")
        await session.commit()


def make_identity_unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], SqlAlchemyIdentityUnitOfWork]:
    def factory() -> SqlAlchemyIdentityUnitOfWork:
        return SqlAlchemyIdentityUnitOfWork(session_factory)

    return factory
