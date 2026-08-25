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
        self._committed = False

    async def __aenter__(self) -> "SqlAlchemyIdentityUnitOfWork":
        self._session = self._session_factory()
        self._committed = False
        self.identities = SqlAlchemyIdentityRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        assert self._session is not None

        try:
            if exc_type is not None or not self._committed:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()
        self._committed = True


def make_identity_unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], SqlAlchemyIdentityUnitOfWork]:
    def factory() -> SqlAlchemyIdentityUnitOfWork:
        return SqlAlchemyIdentityUnitOfWork(session_factory)

    return factory
