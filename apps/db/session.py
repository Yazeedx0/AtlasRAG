from collections.abc import AsyncIterator
from webbrowser import get

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_session,
    async_sessionmaker,
    create_async_engine
)

from apps.core.config import get_settings


settings = get_settings()

engine = create_async_engine(
    str(settings.DATABASE_URL),
    pool_pre_ping=True,
)


async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session