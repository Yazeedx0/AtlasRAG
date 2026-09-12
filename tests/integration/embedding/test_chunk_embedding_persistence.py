from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from atlasrag.contracts.error.embedding_errors import ChunkSetChanged
from atlasrag.contracts.types.embedding import ChunkVector, EmbeddingStatus

from .conftest import (
    DIMENSION,
    LEASE_DURATION,
    default_model_identity,
    embedding_run_configuration,
    stored_embeddings,
    vectors_for,
)

pytestmark = pytest.mark.integration


async def create_claimed_run(world, seeded, *, identity=None):
    model_id = await world.registry.register(identity=identity or default_model_identity())
    run_id = await world.embedding.create_run(
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        configuration=embedding_run_configuration(),
    )
    claim = await world.embedding.claim(run_id=run_id)
    assert claim is not None
    return model_id, run_id, claim


async def complete(world, claim, seeded, model_id, vectors, *, dimension=DIMENSION):
    return await world.embedding.persist_vectors_and_mark_completed(
        run_id=claim.embedding_run_id,
        attempt_number=claim.attempt_number,
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        dimension=dimension,
        expected_chunk_ids=seeded.chunk_ids,
        vectors=vectors,
        execution_metadata={"embedding": {"embedded_chunk_count": len(vectors)}},
    )


@pytest.mark.asyncio
async def test_full_vector_set_is_persisted_and_the_run_completes(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=5)
    model_id, run_id, claim = await create_claimed_run(embedding_world, seeded)

    completed = await complete(
        embedding_world, claim, seeded, model_id, vectors_for(seeded.chunk_ids)
    )
    run = await embedding_world.embedding.find_run(run_id=run_id)
    rows = await stored_embeddings(embedding_world, model_id)

    assert completed is True
    assert run is not None
    assert run.status is EmbeddingStatus.COMPLETED
    assert run.completed_at is not None
    assert run.lease_expires_at is None
    assert run.execution_metadata == {"embedding": {"embedded_chunk_count": 5}}
    assert len(rows) == 5
    assert {row.chunk_id for row in rows} == set(seeded.chunk_ids)
    assert all(len(row.embedding) == DIMENSION for row in rows)
    assert all(row.embedding_run_id == run_id for row in rows)


@pytest.mark.asyncio
async def test_vector_values_round_trip_through_pgvector(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=1)
    model_id, _, claim = await create_claimed_run(embedding_world, seeded)
    values = tuple(float(index) / 4 for index in range(DIMENSION))

    await complete(
        embedding_world,
        claim,
        seeded,
        model_id,
        (ChunkVector(chunk_id=seeded.chunk_ids[0], values=values),),
    )
    rows = await stored_embeddings(embedding_world, model_id)

    assert [pytest.approx(value) for value in rows[0].embedding] == list(values)


@pytest.mark.asyncio
async def test_one_chunk_can_carry_vectors_from_several_models(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=2)
    first_model, _, first_claim = await create_claimed_run(embedding_world, seeded)
    await complete(
        embedding_world, first_claim, seeded, first_model, vectors_for(seeded.chunk_ids)
    )

    second_model, _, second_claim = await create_claimed_run(
        embedding_world,
        seeded,
        identity=default_model_identity(model_revision="v2", dimension=4),
    )
    await complete(
        embedding_world,
        second_claim,
        seeded,
        second_model,
        vectors_for(seeded.chunk_ids, dimension=4),
        dimension=4,
    )

    first_rows = await stored_embeddings(embedding_world, first_model)
    second_rows = await stored_embeddings(embedding_world, second_model)

    assert len(first_rows) == 2
    assert len(second_rows) == 2
    assert {row.chunk_id for row in first_rows} == {row.chunk_id for row in second_rows}
    assert {len(row.embedding) for row in first_rows} == {DIMENSION}
    assert {len(row.embedding) for row in second_rows} == {4}


@pytest.mark.asyncio
async def test_duplicate_vector_for_the_same_chunk_and_model_is_rejected(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=1)
    model_id, _, claim = await create_claimed_run(embedding_world, seeded)
    duplicated = vectors_for(seeded.chunk_ids) + vectors_for(seeded.chunk_ids)

    with pytest.raises(IntegrityError):
        await complete(embedding_world, claim, seeded, model_id, duplicated)

    assert await stored_embeddings(embedding_world, model_id) == []


@pytest.mark.asyncio
async def test_vector_with_the_wrong_dimension_is_rejected_by_the_database(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=1)
    model_id, run_id, claim = await create_claimed_run(embedding_world, seeded)
    mismatched = (ChunkVector(chunk_id=seeded.chunk_ids[0], values=(0.1, 0.2)),)

    with pytest.raises(IntegrityError):
        await complete(embedding_world, claim, seeded, model_id, mismatched)

    run = await embedding_world.embedding.find_run(run_id=run_id)
    assert run is not None
    assert run.status is EmbeddingStatus.RUNNING
    assert await stored_embeddings(embedding_world, model_id) == []


@pytest.mark.asyncio
async def test_partial_vector_set_does_not_complete_the_run(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=4)
    model_id, run_id, claim = await create_claimed_run(embedding_world, seeded)
    partial = vectors_for(seeded.chunk_ids[:2])

    with pytest.raises(ChunkSetChanged):
        await complete(embedding_world, claim, seeded, model_id, partial)

    run = await embedding_world.embedding.find_run(run_id=run_id)
    assert run is not None
    assert run.status is EmbeddingStatus.RUNNING
    assert await stored_embeddings(embedding_world, model_id) == []


@pytest.mark.asyncio
async def test_stale_attempt_cannot_persist_the_final_vectors(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=3)
    model_id, run_id, stale = await create_claimed_run(embedding_world, seeded)
    embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))
    current = await embedding_world.embedding.claim(run_id=run_id)
    assert current is not None

    completed = await complete(
        embedding_world, stale, seeded, model_id, vectors_for(seeded.chunk_ids, value=9.0)
    )
    run = await embedding_world.embedding.find_run(run_id=run_id)

    assert completed is False
    assert run is not None
    assert run.status is EmbeddingStatus.RUNNING
    assert await stored_embeddings(embedding_world, model_id) == []


@pytest.mark.asyncio
async def test_expired_owner_cannot_finalize(embedding_world, seed_completed_item) -> None:
    seeded = await seed_completed_item(chunk_count=2)
    model_id, run_id, claim = await create_claimed_run(embedding_world, seeded)
    embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))

    completed = await complete(
        embedding_world, claim, seeded, model_id, vectors_for(seeded.chunk_ids)
    )
    run = await embedding_world.embedding.find_run(run_id=run_id)

    assert completed is False
    assert run is not None
    assert run.status is EmbeddingStatus.RUNNING
    assert await stored_embeddings(embedding_world, model_id) == []


@pytest.mark.asyncio
async def test_retry_replaces_the_previous_attempt_without_mixing_generations(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=3)
    model_id, run_id, first = await create_claimed_run(embedding_world, seeded)
    await complete(
        embedding_world, first, seeded, model_id, vectors_for(seeded.chunk_ids, value=1.0)
    )

    rerun_id = await embedding_world.embedding.create_run(
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        configuration=embedding_run_configuration(),
    )
    embedding_world.clock.advance(timedelta(seconds=1))
    second = await embedding_world.embedding.claim(run_id=rerun_id)
    assert second is not None
    await complete(
        embedding_world, second, seeded, model_id, vectors_for(seeded.chunk_ids, value=7.0)
    )

    rows = await stored_embeddings(embedding_world, model_id)

    assert len(rows) == 3
    assert {row.embedding_run_id for row in rows} == {rerun_id}
    assert all(row.embedding[0] >= 7.0 for row in rows)
    assert run_id != rerun_id


@pytest.mark.asyncio
async def test_finalization_is_rejected_when_the_chunk_set_moved(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=3)
    other = await seed_completed_item(chunk_count=3)
    model_id, _, claim = await create_claimed_run(embedding_world, seeded)

    with pytest.raises(ChunkSetChanged):
        await embedding_world.embedding.persist_vectors_and_mark_completed(
            run_id=claim.embedding_run_id,
            attempt_number=claim.attempt_number,
            ingestion_item_id=seeded.ingestion_item_id,
            embedding_model_id=model_id,
            dimension=DIMENSION,
            expected_chunk_ids=other.chunk_ids,
            vectors=vectors_for(other.chunk_ids),
            execution_metadata={},
        )

    assert await stored_embeddings(embedding_world, model_id) == []
