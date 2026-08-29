import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from atlasrag.platform.database import Base


def _asyncpg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql+psycopg2://")
    return "postgresql+asyncpg://" + url.removeprefix("postgresql://")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    configured_url = os.getenv("ATLAS_TEST_DATABASE_URL")
    if configured_url is not None:
        yield _asyncpg_url(configured_url)
        return

    with PostgresContainer("postgres:16-alpine") as postgres:
        yield _asyncpg_url(postgres.get_connection_url())


@pytest_asyncio.fixture
async def identity_database(
    postgres_url: str,
) -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(postgres_url, pool_pre_ping=True)

    async with engine.begin() as connection:
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS iam"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        yield engine, session_factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()
