import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from queue import Queue
from uuid import UUID, uuid4

from celery import Task
from celery.contrib.testing.worker import start_worker
from celery.signals import task_prerun
from testcontainers.redis import RedisContainer

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.contracts.types.jobs import ClaimedOutboxJob, JobType
from atlasrag.platform.jobs.celery_app import create_celery_app
from atlasrag.platform.jobs.celery_dispatcher import CeleryTaskDispatcher
from atlasrag.platform.jobs.constants import PROCESS_INGESTION_TASK
from atlasrag.platform.jobs.models import JobOutbox
from atlasrag.platform.jobs.publisher import OutboxPublisher
from atlasrag.platform.jobs.repositories import OutboxRepository
from atlasrag.platform.jobs.unit_of_work import make_job_outbox_unit_of_work_factory


class RecordingDispatcher:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.published: list[tuple[str, dict[str, object]]] = []

    def publish(self, *, task_name: str, payload: dict[str, object]) -> None:
        if self._error is not None:
            raise self._error
        self.published.append((task_name, payload))


class CrashingAfterDispatchPublisher(OutboxPublisher):
    async def _mark_published(self, *, job: ClaimedOutboxJob) -> bool:
        _ = job
        raise RuntimeError("simulated process crash")


@pytest.fixture
def redis_broker_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as redis:
        yield redis.get_connection_url()


def make_publisher(
    session_factory: async_sessionmaker[AsyncSession],
    dispatcher: RecordingDispatcher,
) -> OutboxPublisher:
    return OutboxPublisher(
        make_job_outbox_unit_of_work_factory(session_factory),
        dispatcher,
        lease_duration=timedelta(minutes=1),
        clock=lambda: datetime.now(UTC),
    )


async def add_ingestion_job(
    session: AsyncSession,
    *,
    item_id: UUID | None = None,
) -> UUID:
    ingestion_item_id = item_id or uuid4()
    repository = OutboxRepository(session)
    await repository.enqueue(
        job_id=uuid4(),
        job_type=JobType.PROCESS_INGESTION_ITEM,
        aggregate_id=ingestion_item_id,
        payload={"ingestion_item_id": str(ingestion_item_id)},
    )
    await session.commit()
    return ingestion_item_id


async def get_outbox_job(session: AsyncSession, *, item_id: UUID) -> JobOutbox:
    return (
        await session.execute(
            select(JobOutbox).where(JobOutbox.aggregate_id == item_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_publisher_dispatches_job_and_marks_outbox_row_published(identity_database) -> None:
    _, session_factory = identity_database
    dispatcher = RecordingDispatcher()
    publisher = make_publisher(session_factory, dispatcher)

    async with session_factory() as session:
        item_id = await add_ingestion_job(session)

    report = await publisher.publish_pending(limit=10)

    assert report.claimed == 1
    assert report.published == 1
    assert dispatcher.published == [
        (
            PROCESS_INGESTION_TASK,
            {"ingestion_item_id": str(item_id)},
        )
    ]

    async with session_factory() as session:
        outbox_job = await get_outbox_job(session, item_id=item_id)

    assert outbox_job.published_at is not None
    assert outbox_job.claimed_at is None
    assert outbox_job.lease_expires_at is None


@pytest.mark.asyncio
async def test_broker_failure_keeps_outbox_row_unpublished(identity_database) -> None:
    _, session_factory = identity_database
    dispatcher = RecordingDispatcher(RuntimeError("broker unavailable"))
    publisher = make_publisher(session_factory, dispatcher)

    async with session_factory() as session:
        item_id = await add_ingestion_job(session)

    report = await publisher.publish_pending(limit=10)

    assert report.dispatch_failures == 1

    async with session_factory() as session:
        outbox_job = await get_outbox_job(session, item_id=item_id)

    assert outbox_job.published_at is None
    assert outbox_job.attempt_count == 1
    assert outbox_job.last_error == "dispatch_failed:RuntimeError"


@pytest.mark.asyncio
async def test_unknown_job_type_is_not_dispatched(identity_database) -> None:
    _, session_factory = identity_database
    dispatcher = RecordingDispatcher()
    publisher = make_publisher(session_factory, dispatcher)
    item_id = uuid4()

    async with session_factory() as session:
        await session.execute(
            JobOutbox.__table__.insert().values(
                id=uuid4(),
                job_type="unsupported.job",
                aggregate_id=item_id,
                payload={"ingestion_item_id": str(item_id)},
            )
        )
        await session.commit()

    report = await publisher.publish_pending(limit=10)

    assert report.unknown_job_types == 1
    assert dispatcher.published == []

    async with session_factory() as session:
        outbox_job = await get_outbox_job(session, item_id=item_id)

    assert outbox_job.published_at is None
    assert outbox_job.last_error == "unknown_job_type"


@pytest.mark.asyncio
async def test_published_outbox_row_is_not_dispatched_again(identity_database) -> None:
    _, session_factory = identity_database
    dispatcher = RecordingDispatcher()
    publisher = make_publisher(session_factory, dispatcher)

    async with session_factory() as session:
        await add_ingestion_job(session)

    await publisher.publish_pending(limit=10)
    report = await publisher.publish_pending(limit=10)

    assert report.claimed == 0
    assert len(dispatcher.published) == 1


@pytest.mark.asyncio
async def test_concurrent_publishers_claim_one_outbox_row_once(identity_database) -> None:
    _, session_factory = identity_database
    dispatcher = RecordingDispatcher()
    first = make_publisher(session_factory, dispatcher)
    second = make_publisher(session_factory, dispatcher)

    async with session_factory() as session:
        await add_ingestion_job(session)

    first_report, second_report = await asyncio.gather(
        first.publish_pending(limit=10),
        second.publish_pending(limit=10),
    )

    assert first_report.claimed + second_report.claimed == 1
    assert len(dispatcher.published) == 1


@pytest.mark.asyncio
async def test_crash_after_celery_publish_allows_duplicate_on_retry(identity_database) -> None:
    _, session_factory = identity_database
    dispatcher = RecordingDispatcher()
    crashing_publisher = CrashingAfterDispatchPublisher(
        make_job_outbox_unit_of_work_factory(session_factory),
        dispatcher,
        lease_duration=timedelta(minutes=1),
        clock=lambda: datetime.now(UTC),
    )

    async with session_factory() as session:
        item_id = await add_ingestion_job(session)

    with pytest.raises(RuntimeError, match="simulated process crash"):
        await crashing_publisher.publish_pending(limit=10)

    async with session_factory() as session:
        outbox_job = await get_outbox_job(session, item_id=item_id)

    assert outbox_job.published_at is None
    assert outbox_job.lease_expires_at is not None

    async with session_factory() as session:
        now = datetime.now(UTC)
        await session.execute(
            update(JobOutbox)
            .where(JobOutbox.aggregate_id == item_id)
            .values(
                claimed_at=now - timedelta(minutes=2),
                lease_expires_at=now - timedelta(minutes=1),
            )
        )
        await session.commit()

    retry_publisher = make_publisher(session_factory, dispatcher)
    report = await retry_publisher.publish_pending(limit=10)

    assert report.published == 1
    assert len(dispatcher.published) == 2
    assert dispatcher.published[0] == dispatcher.published[1]

    async with session_factory() as session:
        outbox_job = await get_outbox_job(session, item_id=item_id)

    assert outbox_job.attempt_count == 2
    assert outbox_job.published_at is not None


@pytest.mark.asyncio
async def test_publisher_delivers_outbox_job_to_real_redis_celery_worker(
    identity_database,
    redis_broker_url: str,
) -> None:
    _, session_factory = identity_database
    celery_app = create_celery_app(
        broker_url=redis_broker_url,
        database_url="postgresql+asyncpg://unused:unused@localhost:5432/unused",
        database_echo=False,
        outbox_publish_batch_size=100,
        outbox_publish_lease_seconds=60,
    )
    celery_app.loader.import_default_modules()
    received: Queue[dict[str, object]] = Queue()

    def capture_ingestion_task(
        sender: Task | None = None,
        kwargs: dict[str, object] | None = None,
        **_: object,
    ) -> None:
        if sender is not None and sender.name == PROCESS_INGESTION_TASK:
            received.put(kwargs or {})

    task_prerun.connect(capture_ingestion_task, weak=False)
    try:
        async with session_factory() as session:
            item_id = await add_ingestion_job(session)

        publisher = OutboxPublisher(
            make_job_outbox_unit_of_work_factory(session_factory),
            CeleryTaskDispatcher(celery_app),
            lease_duration=timedelta(minutes=1),
            clock=lambda: datetime.now(UTC),
        )

        with start_worker(celery_app, pool="solo", perform_ping_check=False):
            report = await publisher.publish_pending(limit=10)
            payload = received.get(timeout=10)
    finally:
        task_prerun.disconnect(capture_ingestion_task)

    assert report.published == 1
    assert payload == {"ingestion_item_id": str(item_id)}
