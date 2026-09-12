from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from atlasrag.contracts.error.embedding_errors import (
    EmbeddingRunAlreadyInFlight,
    IngestionItemNotEmbeddable,
)
from atlasrag.contracts.types.embedding import EmbeddingStatus
from atlasrag.contracts.types.jobs import JobType
from atlasrag.modules.embedding.repositories import MAX_ATTEMPTS_EXCEEDED
from atlasrag.platform.jobs.models import JobOutbox

from .conftest import (
    LEASE_DURATION,
    MAX_ATTEMPTS,
    T0,
    default_model_identity,
    embedding_run_configuration,
)

pytestmark = pytest.mark.integration


async def create_run(world, seeded, **overrides):
    model_id = overrides.pop(
        "model_id",
        None,
    ) or await world.registry.register(identity=default_model_identity())
    run_id = await world.embedding.create_run(
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        configuration=embedding_run_configuration(**overrides),
    )
    return model_id, run_id


async def outbox_jobs(world, run_id):
    async with world.session_factory() as session:
        rows = (
            await session.execute(
                select(JobOutbox).where(
                    JobOutbox.job_type == JobType.PROCESS_EMBEDDING.value,
                    JobOutbox.aggregate_id == run_id,
                )
            )
        ).scalars()
        return list(rows)


@pytest.mark.asyncio
async def test_run_is_created_for_a_completed_ingestion_item(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=4)

    model_id, run_id = await create_run(embedding_world, seeded)
    run = await embedding_world.embedding.find_run(run_id=run_id)

    assert run is not None
    assert run.status is EmbeddingStatus.PENDING
    assert run.ingestion_item_id == seeded.ingestion_item_id
    assert run.embedding_model_id == model_id
    assert run.attempt_count == 0
    assert len(run.configuration_hash) == 64


@pytest.mark.asyncio
async def test_run_creation_is_rejected_for_an_incomplete_ingestion_item(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(complete=False)
    model_id = await embedding_world.registry.register(identity=default_model_identity())

    with pytest.raises(IngestionItemNotEmbeddable):
        await embedding_world.embedding.create_run(
            ingestion_item_id=seeded.ingestion_item_id,
            embedding_model_id=model_id,
            configuration=embedding_run_configuration(),
        )


@pytest.mark.asyncio
async def test_run_creation_enqueues_an_outbox_job_in_the_same_transaction(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()

    _, run_id = await create_run(embedding_world, seeded)
    jobs = await outbox_jobs(embedding_world, run_id)

    assert len(jobs) == 1
    assert jobs[0].payload == {"embedding_run_id": str(run_id)}
    assert jobs[0].published_at is None


@pytest.mark.asyncio
async def test_a_second_in_flight_run_for_the_same_model_is_rejected(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()
    model_id, _ = await create_run(embedding_world, seeded)

    with pytest.raises(EmbeddingRunAlreadyInFlight):
        await embedding_world.embedding.create_run(
            ingestion_item_id=seeded.ingestion_item_id,
            embedding_model_id=model_id,
            configuration=embedding_run_configuration(),
        )


@pytest.mark.asyncio
async def test_the_same_chunks_can_be_embedded_by_a_second_model(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()
    _, first_run = await create_run(embedding_world, seeded)
    second_model = await embedding_world.registry.register(
        identity=default_model_identity(model_revision="v2")
    )

    second_run = await embedding_world.embedding.create_run(
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=second_model,
        configuration=embedding_run_configuration(),
    )

    assert first_run != second_run


@pytest.mark.asyncio
async def test_a_new_run_is_allowed_once_the_previous_one_failed(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()
    model_id, run_id = await create_run(embedding_world, seeded)
    claim = await embedding_world.embedding.claim(run_id=run_id)
    assert claim is not None
    await embedding_world.embedding.mark_failed(
        run_id=run_id,
        attempt_number=claim.attempt_number,
        error_code="embedding_provider_failed",
    )

    rerun_id = await embedding_world.embedding.create_run(
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        configuration=embedding_run_configuration(),
    )

    assert rerun_id != run_id


@pytest.mark.asyncio
async def test_pending_run_can_be_claimed(embedding_world, seed_completed_item) -> None:
    seeded = await seed_completed_item()
    model_id, run_id = await create_run(embedding_world, seeded)

    claim = await embedding_world.embedding.claim(run_id=run_id)

    assert claim is not None
    assert claim.embedding_run_id == run_id
    assert claim.ingestion_item_id == seeded.ingestion_item_id
    assert claim.embedding_model_id == model_id
    assert claim.attempt_number == 1
    assert claim.claimed_at == T0
    assert claim.lease_expires_at == T0 + LEASE_DURATION


@pytest.mark.asyncio
async def test_live_lease_cannot_be_stolen(embedding_world, seed_completed_item) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)
    await embedding_world.embedding.claim(run_id=run_id)

    embedding_world.clock.advance(timedelta(seconds=30))
    second = await embedding_world.embedding.claim(run_id=run_id)

    assert second is None


@pytest.mark.asyncio
async def test_expired_lease_can_be_reclaimed_with_a_new_fencing_token(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)
    first = await embedding_world.embedding.claim(run_id=run_id)
    assert first is not None

    embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))
    second = await embedding_world.embedding.claim(run_id=run_id)
    run = await embedding_world.embedding.find_run(run_id=run_id)

    assert second is not None
    assert second.attempt_number == first.attempt_number + 1
    assert run is not None
    assert run.started_at == T0


@pytest.mark.asyncio
async def test_stale_attempt_cannot_heartbeat(embedding_world, seed_completed_item) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)
    first = await embedding_world.embedding.claim(run_id=run_id)
    assert first is not None
    embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))
    await embedding_world.embedding.claim(run_id=run_id)

    renewed = await embedding_world.embedding.heartbeat(
        run_id=run_id,
        attempt_number=first.attempt_number,
    )

    assert renewed is False


@pytest.mark.asyncio
async def test_expired_owner_cannot_heartbeat(embedding_world, seed_completed_item) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)
    claim = await embedding_world.embedding.claim(run_id=run_id)
    assert claim is not None

    embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))
    renewed = await embedding_world.embedding.heartbeat(
        run_id=run_id,
        attempt_number=claim.attempt_number,
    )

    assert renewed is False


@pytest.mark.asyncio
async def test_owner_heartbeat_extends_the_lease(embedding_world, seed_completed_item) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)
    claim = await embedding_world.embedding.claim(run_id=run_id)
    assert claim is not None

    embedding_world.clock.advance(timedelta(minutes=1))
    renewed = await embedding_world.embedding.heartbeat(
        run_id=run_id,
        attempt_number=claim.attempt_number,
    )
    run = await embedding_world.embedding.find_run(run_id=run_id)

    assert renewed is True
    assert run is not None
    assert run.lease_expires_at == T0 + timedelta(minutes=1) + LEASE_DURATION


@pytest.mark.asyncio
async def test_stale_attempt_cannot_mark_failed(embedding_world, seed_completed_item) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)
    first = await embedding_world.embedding.claim(run_id=run_id)
    assert first is not None
    embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))
    await embedding_world.embedding.claim(run_id=run_id)

    failed = await embedding_world.embedding.mark_failed(
        run_id=run_id,
        attempt_number=first.attempt_number,
        error_code="embedding_provider_failed",
    )
    run = await embedding_world.embedding.find_run(run_id=run_id)

    assert failed is False
    assert run is not None
    assert run.status is EmbeddingStatus.RUNNING


@pytest.mark.asyncio
async def test_transient_failure_schedules_a_durable_retry(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)
    claim = await embedding_world.embedding.claim(run_id=run_id)
    assert claim is not None

    scheduled = await embedding_world.embedding.schedule_retry(
        run_id=run_id,
        attempt_number=claim.attempt_number,
        error_code="transient_embedding_error",
    )
    run = await embedding_world.embedding.find_run(run_id=run_id)
    jobs = await outbox_jobs(embedding_world, run_id)

    assert scheduled is True
    assert run is not None
    assert run.status is EmbeddingStatus.PENDING
    assert run.claimed_at is None
    assert run.lease_expires_at is None
    assert run.attempt_count == 1
    assert len(jobs) == 2
    assert sum(1 for job in jobs if job.failure_code == "superseded_by_retry") == 1


@pytest.mark.asyncio
async def test_retry_on_the_final_attempt_fails_instead_of_stranding(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)

    for _ in range(MAX_ATTEMPTS):
        claim = await embedding_world.embedding.claim(run_id=run_id)
        assert claim is not None
        await embedding_world.embedding.schedule_retry(
            run_id=run_id,
            attempt_number=claim.attempt_number,
            error_code="transient_embedding_error",
        )
        embedding_world.clock.advance(timedelta(seconds=1))

    run = await embedding_world.embedding.find_run(run_id=run_id)
    exhausted = await embedding_world.embedding.claim(run_id=run_id)

    assert run is not None
    assert run.status is EmbeddingStatus.FAILED
    assert run.error_code == MAX_ATTEMPTS_EXCEEDED
    assert exhausted is None


@pytest.mark.asyncio
async def test_expired_exhausted_run_is_reaped_as_failed(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)
    for _ in range(MAX_ATTEMPTS):
        claim = await embedding_world.embedding.claim(run_id=run_id)
        assert claim is not None
        embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))

    reaped = await embedding_world.embedding.reap_expired_runs()
    run = await embedding_world.embedding.find_run(run_id=run_id)

    assert reaped == 1
    assert run is not None
    assert run.status is EmbeddingStatus.FAILED
    assert run.error_code == MAX_ATTEMPTS_EXCEEDED
    assert run.lease_expires_at is None


@pytest.mark.asyncio
async def test_reaper_leaves_runs_with_attempts_remaining(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item()
    _, run_id = await create_run(embedding_world, seeded)
    await embedding_world.embedding.claim(run_id=run_id)
    embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))

    reaped = await embedding_world.embedding.reap_expired_runs()
    run = await embedding_world.embedding.find_run(run_id=run_id)

    assert reaped == 0
    assert run is not None
    assert run.status is EmbeddingStatus.RUNNING


@pytest.mark.asyncio
async def test_unknown_run_cannot_be_claimed(embedding_world) -> None:
    assert await embedding_world.embedding.claim(run_id=uuid4()) is None
