import asyncio
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atlasrag.bootstrap.core.config import get_settings
from atlasrag.modules.embedding._vector_index import vector_index_name

pytestmark = pytest.mark.integration


async def add_model(database_url: str, model_id: UUID) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO knowledge.embedding_models "
                    "(id, provider, model_name, model_revision, dimension, distance_metric, "
                    "configuration_hash) "
                    "VALUES (:id, 'openai', 'text-embedding-3-small', 'v1', 1536, 'cosine', :hash)"
                ),
                {"id": model_id, "hash": "c" * 64},
            )
    finally:
        await engine.dispose()


async def retrieval_indexes_exist(database_url: str, model_id: UUID) -> tuple[bool, bool]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            has_search_vector = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'knowledge' AND table_name = 'chunks' "
                    "AND column_name = 'search_vector')"
                )
            )
            has_vector_index = await connection.scalar(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"knowledge.{vector_index_name(model_id=model_id)}"},
            )
            return has_search_vector is True, has_vector_index is True
    finally:
        await engine.dispose()


def test_retrieval_index_migration_backfills_and_drops_indexes(
    postgres_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_DATABASE_URL", postgres_url)
    get_settings.cache_clear()
    configuration = Config("alembic.ini")
    model_id = uuid4()

    try:
        command.upgrade(configuration, "0028")
        asyncio.run(add_model(postgres_url, model_id))

        command.upgrade(configuration, "0029")
        assert asyncio.run(retrieval_indexes_exist(postgres_url, model_id)) == (True, True)

        command.downgrade(configuration, "0028")
        assert asyncio.run(retrieval_indexes_exist(postgres_url, model_id)) == (False, False)
    finally:
        command.downgrade(configuration, "base")
        get_settings.cache_clear()
