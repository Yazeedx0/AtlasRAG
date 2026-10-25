from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from atlasrag.modules.embedding._vector_index import vector_index_name
from atlasrag.modules.ingestion.models import Chunk

from .conftest import default_model_identity

pytestmark = pytest.mark.integration


async def index_definition(embedding_world, model_id: UUID) -> str | None:
    async with embedding_world.session_factory() as session:
        return await session.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
            {"name": vector_index_name(model_id=model_id)},
        )


async def add_chunk(embedding_world, *, item_id: UUID, index: int, content: str, language: str) -> UUID:
    chunk_id = uuid4()
    async with embedding_world.session_factory() as session:
        await session.execute(
            Chunk.__table__.insert().values(
                id=chunk_id,
                ingestion_item_id=item_id,
                chunk_index=index,
                content=content,
                content_type="text",
                language_code=language,
                token_count=len(content.split()),
                content_hash=uuid4().hex * 2,
            )
        )
        await session.commit()
    return chunk_id


async def search(embedding_world, query_config: str, query: str) -> set[UUID]:
    async with embedding_world.session_factory() as session:
        rows = await session.scalars(
            text(
                "SELECT id FROM knowledge.chunks "
                "WHERE search_vector @@ plainto_tsquery(CAST(CAST(:config AS text) AS regconfig), :query)"
            ),
            {"config": query_config, "query": query},
        )
        return set(rows)


@pytest.mark.asyncio
async def test_registering_a_model_creates_a_partial_hnsw_index(embedding_world) -> None:
    model_id = await embedding_world.registry.register(
        identity=default_model_identity(dimension=1536)
    )

    definition = await index_definition(embedding_world, model_id)

    assert definition is not None
    assert "USING hnsw" in definition
    assert "vector_cosine_ops" in definition
    assert str(model_id) in definition


@pytest.mark.asyncio
async def test_registering_the_same_model_twice_keeps_one_index(embedding_world) -> None:
    identity = default_model_identity(dimension=1536)

    first = await embedding_world.registry.register(identity=identity)
    second = await embedding_world.registry.register(identity=identity)

    assert first == second
    assert await index_definition(embedding_world, first) is not None


@pytest.mark.asyncio
async def test_model_above_index_limit_is_registered_without_an_index(embedding_world) -> None:
    model_id = await embedding_world.registry.register(
        identity=default_model_identity(dimension=4096, model_name="oversized")
    )

    assert await embedding_world.registry.find_model(model_id=model_id) is not None
    assert await index_definition(embedding_world, model_id) is None


@pytest.mark.asyncio
async def test_english_chunks_match_stemmed_queries(embedding_world, seed_completed_item) -> None:
    seeded = await seed_completed_item(chunk_count=1)
    leave = await add_chunk(
        embedding_world,
        item_id=seeded.ingestion_item_id,
        index=10,
        content="Employees are entitled to paid vacations every year.",
        language="en",
    )
    other = await add_chunk(
        embedding_world,
        item_id=seeded.ingestion_item_id,
        index=11,
        content="Expense reports must be filed monthly.",
        language="en",
    )

    matches = await search(embedding_world, "english", "vacation")

    assert leave in matches
    assert other not in matches


@pytest.mark.asyncio
async def test_arabic_chunks_are_indexed_with_the_arabic_configuration(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=1)
    leave = await add_chunk(
        embedding_world,
        item_id=seeded.ingestion_item_id,
        index=10,
        content="يحق للموظف إجازة سنوية مدفوعة",
        language="ar",
    )
    other = await add_chunk(
        embedding_world,
        item_id=seeded.ingestion_item_id,
        index=11,
        content="تقدم تقارير المصروفات شهريا",
        language="ar",
    )

    matches = await search(embedding_world, "arabic", "إجازة")

    assert leave in matches
    assert other not in matches
