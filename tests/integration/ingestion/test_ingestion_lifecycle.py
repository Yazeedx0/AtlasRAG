import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import literal
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types.ingestion import IngestionStatus
from atlasrag.modules.ingestion.repositories import (
    MAX_ATTEMPTS_EXCEEDED,
    IngestionRepository,
)
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.knowledge.models import (
    Document,
    DocumentArtifact,
    DocumentVersion,
)

LEASE_DURATION = timedelta(minutes=2)
MAX_ATTEMPTS = 3
T0 = datetime(2026, 9, 1, 18, 10, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


async def add_artifact(session: AsyncSession) -> UUID:
    document_id = uuid4()
    version_id = uuid4()
    artifact_id = uuid4()

    await session.execute(
        Document.__table__.insert().values(
            id=document_id,
            canonical_key=f"canonical-{document_id}",
            title="Lifecycle fixture",
        )
    )
    await session.execute(
        DocumentVersion.__table__.insert().values(
            id=version_id,
            document_id=document_id,
            version_label="v1",
        )
    )
    await session.execute(
        DocumentArtifact.__table__.insert().values(
            id=artifact_id,
            document_version_id=version_id,
            artifact_key=f"artifact-{artifact_id}",
            language_code="en",
            source_name="fixture.pdf",
            storage_provider="s3",
            storage_key=f"key/{artifact_id}",
            mime_type="application/pdf",
            file_hash="a" * 64,
            file_size_bytes=1024,
        )
    )
    return artifact_id


def make_service(
    session: AsyncSession,
    clock: FakeClock,
) -> IngestionLifecycleService:
    return IngestionLifecycleService(
        IngestionRepository(session, db_time=lambda: literal(clock())),
        lease_duration=LEASE_DURATION,
        max_attempts=MAX_ATTEMPTS,
        clock=clock,
    )


async def setup_item(
    session: AsyncSession,
    service: IngestionLifecycleService,
) -> UUID:
    artifact_id = await add_artifact(session)
    run_id = await service.create_run(
        configuration={"chunking": {"strategy": "heading_aware_v1"}},
        configuration_hash="b" * 64,
        created_by_principal_id=None,
    )
    return await service.add_item(
        ingestion_run_id=run_id,
        document_artifact_id=artifact_id,
    )


@pytest.mark.asyncio
async def test_pending_item_can_be_claimed(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        claim = await service.claim(item_id=item_id)

    assert claim is not None
    assert claim.ingestion_item_id == item_id
    assert claim.attempt_number == 1
    assert claim.claimed_at == T0
    assert claim.lease_expires_at == T0 + LEASE_DURATION


@pytest.mark.asyncio
async def test_first_claim_sets_started_at(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        await service.claim(item_id=item_id)
        item = await service.find_item(item_id=item_id)

    assert item is not None
    assert item.started_at == T0
    assert item.status is IngestionStatus.RUNNING


@pytest.mark.asyncio
async def test_reclaim_does_not_reset_started_at(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        await service.claim(item_id=item_id)
        clock.advance(LEASE_DURATION + timedelta(minutes=1))
        second = await service.claim(item_id=item_id)
        item = await service.find_item(item_id=item_id)

    assert second is not None
    assert item is not None
    assert item.started_at == T0
    assert item.claimed_at == T0 + LEASE_DURATION + timedelta(minutes=1)


@pytest.mark.asyncio
async def test_reclaim_increments_fencing_token(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        first = await service.claim(item_id=item_id)
        clock.advance(LEASE_DURATION + timedelta(minutes=1))
        second = await service.claim(item_id=item_id)

    assert first is not None
    assert second is not None
    assert first.attempt_number == 1
    assert second.attempt_number == 2


@pytest.mark.asyncio
async def test_running_item_with_live_lease_cannot_be_claimed(
    identity_database,
) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        await service.claim(item_id=item_id)
        clock.advance(timedelta(seconds=30))
        second = await service.claim(item_id=item_id)

    assert second is None


@pytest.mark.asyncio
async def test_expired_running_item_can_be_reclaimed(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        await service.claim(item_id=item_id)
        clock.advance(LEASE_DURATION + timedelta(seconds=1))
        second = await service.claim(item_id=item_id)

    assert second is not None
    assert second.attempt_number == 2


@pytest.mark.asyncio
async def test_heartbeat_extends_valid_lease(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        claim = await service.claim(item_id=item_id)
        assert claim is not None

        clock.advance(timedelta(minutes=1))
        extended = await service.heartbeat(
            item_id=item_id,
            attempt_number=claim.attempt_number,
        )
        item = await service.find_item(item_id=item_id)

    assert extended is True
    assert item is not None
    assert item.lease_expires_at == T0 + timedelta(minutes=1) + LEASE_DURATION


@pytest.mark.asyncio
async def test_stale_attempt_cannot_heartbeat(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        first = await service.claim(item_id=item_id)
        assert first is not None

        clock.advance(LEASE_DURATION + timedelta(seconds=1))
        await service.claim(item_id=item_id)

        extended = await service.heartbeat(
            item_id=item_id,
            attempt_number=first.attempt_number,
        )

    assert extended is False


@pytest.mark.asyncio
async def test_expired_worker_cannot_heartbeat_before_reclaim(
    identity_database,
) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        claim = await service.claim(item_id=item_id)
        assert claim is not None

        clock.advance(LEASE_DURATION + timedelta(seconds=1))
        extended = await service.heartbeat(
            item_id=item_id,
            attempt_number=claim.attempt_number,
        )

    assert extended is False


@pytest.mark.asyncio
async def test_stale_attempt_cannot_fail(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        first = await service.claim(item_id=item_id)
        assert first is not None

        clock.advance(LEASE_DURATION + timedelta(seconds=1))
        await service.claim(item_id=item_id)

        failed = await service.mark_failed(
            item_id=item_id,
            attempt_number=first.attempt_number,
            error_code="extraction_failed",
        )
        item = await service.find_item(item_id=item_id)

    assert failed is False
    assert item is not None
    assert item.status is IngestionStatus.RUNNING


@pytest.mark.asyncio
async def test_owner_can_mark_failed(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        claim = await service.claim(item_id=item_id)
        assert claim is not None

        failed = await service.mark_failed(
            item_id=item_id,
            attempt_number=claim.attempt_number,
            error_code="artifact_integrity_mismatch",
            error_message="sha mismatch",
        )
        item = await service.find_item(item_id=item_id)

    assert failed is True
    assert item is not None
    assert item.status is IngestionStatus.FAILED
    assert item.completed_at == T0
    assert item.claimed_at is None
    assert item.lease_expires_at is None
    assert item.error_code == "artifact_integrity_mismatch"


@pytest.mark.asyncio
async def test_owner_can_release_for_retry(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        claim = await service.claim(item_id=item_id)
        assert claim is not None

        released = await service.release_for_retry(
            item_id=item_id,
            attempt_number=claim.attempt_number,
            error_code="provider_unavailable",
        )
        item = await service.find_item(item_id=item_id)

    assert released is True
    assert item is not None
    assert item.status is IngestionStatus.PENDING
    assert item.claimed_at is None
    assert item.lease_expires_at is None
    assert item.attempt_count == 1


@pytest.mark.asyncio
async def test_stale_attempt_cannot_release(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        first = await service.claim(item_id=item_id)
        assert first is not None

        clock.advance(LEASE_DURATION + timedelta(seconds=1))
        await service.claim(item_id=item_id)

        released = await service.release_for_retry(
            item_id=item_id,
            attempt_number=first.attempt_number,
        )

    assert released is False


@pytest.mark.asyncio
async def test_released_item_can_be_claimed_again(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        first = await service.claim(item_id=item_id)
        assert first is not None
        await service.release_for_retry(
            item_id=item_id,
            attempt_number=first.attempt_number,
        )

        clock.advance(timedelta(seconds=5))
        second = await service.claim(item_id=item_id)

    assert second is not None
    assert second.attempt_number == 2


@pytest.mark.asyncio
async def test_failed_item_cannot_be_claimed(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        claim = await service.claim(item_id=item_id)
        assert claim is not None
        await service.mark_failed(
            item_id=item_id,
            attempt_number=claim.attempt_number,
            error_code="permanent",
        )

        clock.advance(timedelta(hours=1))
        again = await service.claim(item_id=item_id)

    assert again is None


@pytest.mark.asyncio
async def test_max_attempts_prevents_another_claim(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        for _ in range(MAX_ATTEMPTS):
            claim = await service.claim(item_id=item_id)
            assert claim is not None
            await service.release_for_retry(
                item_id=item_id,
                attempt_number=claim.attempt_number,
            )
            clock.advance(timedelta(seconds=1))

        exhausted = await service.claim(item_id=item_id)
        item = await service.find_item(item_id=item_id)

    assert exhausted is None
    assert item is not None
    assert item.attempt_count == MAX_ATTEMPTS
    assert item.status is IngestionStatus.FAILED
    assert item.error_code == MAX_ATTEMPTS_EXCEEDED


@pytest.mark.asyncio
async def test_release_on_final_attempt_fails_instead_of_stranding(
    identity_database,
) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        for _ in range(MAX_ATTEMPTS - 1):
            claim = await service.claim(item_id=item_id)
            assert claim is not None
            released = await service.release_for_retry(
                item_id=item_id,
                attempt_number=claim.attempt_number,
            )
            assert released is True
            clock.advance(timedelta(seconds=1))

        final = await service.claim(item_id=item_id)
        assert final is not None
        assert final.attempt_number == MAX_ATTEMPTS

        released = await service.release_for_retry(
            item_id=item_id,
            attempt_number=final.attempt_number,
            error_code="provider_unavailable",
        )
        item = await service.find_item(item_id=item_id)

    assert released is True
    assert item is not None
    assert item.status is IngestionStatus.FAILED
    assert item.error_code == MAX_ATTEMPTS_EXCEEDED
    assert item.completed_at == T0 + timedelta(seconds=MAX_ATTEMPTS - 1)
    assert item.claimed_at is None
    assert item.lease_expires_at is None


@pytest.mark.asyncio
async def test_stranded_pending_item_is_never_produced_by_retry_loop(
    identity_database,
) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        for _ in range(MAX_ATTEMPTS):
            claim = await service.claim(item_id=item_id)
            if claim is None:
                break
            await service.release_for_retry(
                item_id=item_id,
                attempt_number=claim.attempt_number,
            )
            clock.advance(timedelta(seconds=1))

        clock.advance(timedelta(days=1))
        await service.reap_expired_items()
        item = await service.find_item(item_id=item_id)

    assert item is not None
    assert item.status is not IngestionStatus.PENDING
    assert item.status is IngestionStatus.FAILED


@pytest.mark.asyncio
async def test_expired_max_attempt_item_becomes_failed(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        for _ in range(MAX_ATTEMPTS):
            claim = await service.claim(item_id=item_id)
            assert claim is not None
            clock.advance(LEASE_DURATION + timedelta(seconds=1))

        stuck = await service.find_item(item_id=item_id)
        assert stuck is not None
        assert stuck.status is IngestionStatus.RUNNING
        assert stuck.attempt_count == MAX_ATTEMPTS

        reaped = await service.reap_expired_items()
        item = await service.find_item(item_id=item_id)

    assert reaped == 1
    assert item is not None
    assert item.status is IngestionStatus.FAILED
    assert item.error_code == MAX_ATTEMPTS_EXCEEDED
    assert item.claimed_at is None
    assert item.lease_expires_at is None


@pytest.mark.asyncio
async def test_reaper_leaves_items_with_attempts_remaining(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)

        await service.claim(item_id=item_id)
        clock.advance(LEASE_DURATION + timedelta(seconds=1))

        reaped = await service.reap_expired_items()
        item = await service.find_item(item_id=item_id)

    assert reaped == 0
    assert item is not None
    assert item.status is IngestionStatus.RUNNING


@pytest.mark.asyncio
async def test_find_expired_items_returns_only_expired(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        repository = IngestionRepository(session, db_time=lambda: literal(clock()))

        expired_id = await setup_item(session, service)
        live_id = await setup_item(session, service)

        await service.claim(item_id=expired_id)
        clock.advance(LEASE_DURATION + timedelta(seconds=1))
        await service.claim(item_id=live_id)

        expired = await repository.find_expired_items(limit=10)

    assert tuple(state.id for state in expired) == (expired_id,)


@pytest.mark.asyncio
async def test_concurrent_claims_yield_exactly_one_winner(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id = await setup_item(session, service)
        await session.commit()

    async def attempt_claim() -> object:
        async with session_factory() as session:
            service = make_service(session, FakeClock(T0))
            claim = await service.claim(item_id=item_id)
            await session.commit()
            return claim

    results = await asyncio.gather(*(attempt_claim() for _ in range(8)))

    winners = [claim for claim in results if claim is not None]
    assert len(winners) == 1
    assert winners[0].attempt_number == 1

    async with session_factory() as session:
        service = make_service(session, FakeClock(T0))
        item = await service.find_item(item_id=item_id)

    assert item is not None
    assert item.attempt_count == 1
    assert item.status is IngestionStatus.RUNNING
