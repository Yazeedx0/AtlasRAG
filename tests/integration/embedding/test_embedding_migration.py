import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atlasrag.bootstrap.core.config import get_settings

pytestmark = pytest.mark.integration


async def embedding_tables_exist(database_url: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return (
                await connection.scalar(
                    text(
                        "SELECT to_regclass('knowledge.embedding_models') IS NOT NULL "
                        "AND to_regclass('knowledge.embedding_runs') IS NOT NULL "
                        "AND to_regclass('knowledge.chunk_embeddings') IS NOT NULL"
                    )
                )
            ) is True
    finally:
        await engine.dispose()


def test_embedding_migrations_create_and_drop_schema(
    postgres_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_DATABASE_URL", postgres_url)
    get_settings.cache_clear()
    configuration = Config("alembic.ini")

    try:
        command.upgrade(configuration, "0028")
        assert asyncio.run(embedding_tables_exist(postgres_url))

        command.downgrade(configuration, "0026")
        assert not asyncio.run(embedding_tables_exist(postgres_url))
    finally:
        command.downgrade(configuration, "base")
        get_settings.cache_clear()
