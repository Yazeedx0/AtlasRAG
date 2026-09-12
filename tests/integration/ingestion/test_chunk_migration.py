import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atlasrag.bootstrap.core.config import get_settings


async def chunk_table_exists(database_url: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return (
                await connection.scalar(text("SELECT to_regclass('knowledge.chunks') IS NOT NULL"))
            ) is True
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_chunk_migration_creates_and_drops_table(
    postgres_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_DATABASE_URL", postgres_url)
    get_settings.cache_clear()
    configuration = Config("alembic.ini")

    try:
        command.upgrade(configuration, "0026")
        assert asyncio.run(chunk_table_exists(postgres_url))

        command.downgrade(configuration, "0025")
        assert not asyncio.run(chunk_table_exists(postgres_url))
    finally:
        command.downgrade(configuration, "base")
        get_settings.cache_clear()
