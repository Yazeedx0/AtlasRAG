from datetime import timedelta

import pytest
from sqlalchemy import literal, update

from atlasrag.contracts.types.embedding import EmbeddingStatus
from atlasrag.modules.embedding.models import EmbeddingRun
from atlasrag.modules.embedding.repositories import make_embedding_unit_of_work_factory
from atlasrag.modules.embedding.services import EmbeddingRecoveryService
from atlasrag.modules.ingestion.repositories import EmbeddableChunkRepository

from .conftest import (
    LEASE_DURATION,
    default_model_identity,
    embedding_run_configuration,
)

pytestmark = pytest.mark.integration


def make_recovery(world) -> EmbeddingRecoveryService:
    uow_factory = make_embedding_unit_of_work_factory(
        world.session_factory,
        chunk_source_factory=EmbeddableChunkRepository,
        db_time=lambda: literal(world.clock()),
    )
    return EmbeddingRecoveryService(
        uow_factory=uow_factory,
        lifecycle=world.embedding,
        dispatcher=world.dispatcher,
        pending_age=timedelta(seconds=30),
        batch_size=10,
        clock=world.clock,
    )


async def create_run(world, seeded):
    model_id = await world.registry.register(identity=default_model_identity())
    return await world.embedding.create_run(
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        configuration=embedding_run_configuration(),
    )


async def age_run(world, run_id) -> None:
    async with world.session_factory() as session:
        await session.execute(
            update(EmbeddingRun)
            .where(EmbeddingRun.id == run_id)
            .values(created_at=world.clock() - timedelta(seconds=31))
        )
        await session.commit()


@pytest.mark.asyncio
async def test_enqueue_failure_leaves_the_committed_run_pending_for_recovery(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()
    embedding_world.dispatcher.failure = RuntimeError("redis unavailable")

    run_id = await create_run(embedding_world, seeded)
    run = await embedding_world.embedding.find_run(run_id=run_id)

    assert run is not None
    assert run.status is EmbeddingStatus.PENDING
    assert embedding_world.dispatcher.dispatched == []

    embedding_world.dispatcher.failure = None
    await age_run(embedding_world, run_id)
    report = await make_recovery(embedding_world).recover()

    assert report.redispatched_pending == 1
    assert embedding_world.dispatcher.dispatched == [run_id]


@pytest.mark.asyncio
async def test_recent_pending_run_is_not_redispatched(embedding_world, seed_completed_item) -> None:
    run_id = await create_run(embedding_world, await seed_completed_item())
    embedding_world.dispatcher.dispatched.clear()

    report = await make_recovery(embedding_world).recover()

    assert report.redispatched_pending == 0
    assert embedding_world.dispatcher.dispatched == []
    assert await embedding_world.embedding.find_run(run_id=run_id) is not None


@pytest.mark.asyncio
async def test_expired_lease_is_redispatched_when_attempts_remain(
    embedding_world, seed_completed_item
) -> None:
    run_id = await create_run(embedding_world, await seed_completed_item())
    claim = await embedding_world.embedding.claim(run_id=run_id)
    assert claim is not None
    embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))
    embedding_world.dispatcher.dispatched.clear()

    report = await make_recovery(embedding_world).recover()

    assert report.redispatched_expired == 1
    assert embedding_world.dispatcher.dispatched == [run_id]
