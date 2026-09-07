from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID, uuid4

import pytest
from tests.unit.conftest import ObservabilityHarness

from atlasrag.contracts.jobs import JobOutboxUnitOfWork
from atlasrag.contracts.types.jobs import ClaimedOutboxJob, JobType
from atlasrag.contracts.types.observability import LabelKey, MetricName, SpanName
from atlasrag.platform.jobs.publisher import OutboxPublisher

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


class FakeOutboxRepository:
    def __init__(
        self,
        *,
        jobs: list[ClaimedOutboxJob],
        pending: dict[str, int],
        publishable: bool = True,
    ) -> None:
        self._jobs = jobs
        self._pending = pending
        self._publishable = publishable
        self.published: list[UUID] = []
        self.failed: list[tuple[UUID, str]] = []
        self.released: list[tuple[UUID, str]] = []

    async def claim_unpublished_batch(
        self,
        *,
        limit: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> tuple[ClaimedOutboxJob, ...]:
        claimed = tuple(self._jobs[:limit])
        self._jobs = self._jobs[limit:]
        return claimed

    async def mark_published(
        self,
        *,
        job_id: UUID,
        attempt_number: int,
        published_at: datetime,
    ) -> bool:
        if not self._publishable:
            return False
        self.published.append(job_id)
        return True

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        attempt_number: int,
        failed_at: datetime,
        failure_code: str,
    ) -> bool:
        self.failed.append((job_id, failure_code))
        return True

    async def release_publish_claim(
        self,
        *,
        job_id: UUID,
        attempt_number: int,
        error_code: str,
    ) -> bool:
        self.released.append((job_id, error_code))
        return True

    async def count_pending_by_job_type(self) -> dict[str, int]:
        return dict(self._pending)

    async def enqueue(self, **kwargs: object) -> None:
        return None

    async def discard_pending_for_aggregate(self, **kwargs: object) -> int:
        return 0


class FakeUnitOfWork:
    def __init__(self, repository: FakeOutboxRepository) -> None:
        self.outbox = repository

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None


class RecordingDispatcher:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.published: list[str] = []

    def publish(self, *, task_name: str, payload: dict[str, object]) -> None:
        if self._error is not None:
            raise self._error
        self.published.append(task_name)


def make_job(job_type: str = JobType.PROCESS_INGESTION_ITEM.value) -> ClaimedOutboxJob:
    return ClaimedOutboxJob(
        id=uuid4(),
        job_type=job_type,
        aggregate_id=uuid4(),
        payload={"ingestion_item_id": str(uuid4())},
        attempt_number=1,
        lease_expires_at=_NOW + timedelta(seconds=60),
    )


def make_publisher(
    repository: FakeOutboxRepository,
    dispatcher: RecordingDispatcher,
) -> OutboxPublisher:
    def factory() -> JobOutboxUnitOfWork:
        return FakeUnitOfWork(repository)  # type: ignore[return-value]

    return OutboxPublisher(
        factory,
        dispatcher,
        lease_duration=timedelta(seconds=60),
        clock=lambda: _NOW,
    )


async def test_a_successful_publish_emits_its_spans_and_counters(
    observability: ObservabilityHarness,
) -> None:
    repository = FakeOutboxRepository(jobs=[make_job()], pending={})
    publisher = make_publisher(repository, RecordingDispatcher())

    report = await publisher.publish_pending(limit=10)

    assert report.published == 1
    names = observability.span_names()
    assert SpanName.OUTBOX_CLAIM.value in names
    assert SpanName.OUTBOX_PUBLISH.value in names
    assert SpanName.OUTBOX_MARK_PUBLISHED.value in names

    labels = {LabelKey.JOB_TYPE: JobType.PROCESS_INGESTION_ITEM.value}
    assert (
        observability.metrics.counter_value(MetricName.OUTBOX_PUBLISH_ATTEMPTS_TOTAL, labels=labels)
        == 1
    )
    assert (
        observability.metrics.counter_value(MetricName.OUTBOX_PUBLISH_SUCCESS_TOTAL, labels=labels)
        == 1
    )


async def test_a_broker_failure_is_counted_under_a_bounded_error_code(
    observability: ObservabilityHarness,
) -> None:
    repository = FakeOutboxRepository(jobs=[make_job()], pending={})
    dispatcher = RecordingDispatcher(ConnectionResetError("broker connection reset"))
    publisher = make_publisher(repository, dispatcher)

    report = await publisher.publish_pending(limit=10)

    assert report.dispatch_failures == 1
    assert (
        observability.metrics.counter_value(
            MetricName.OUTBOX_PUBLISH_FAILURE_TOTAL,
            labels={
                LabelKey.JOB_TYPE: JobType.PROCESS_INGESTION_ITEM.value,
                LabelKey.ERROR_CODE: "dispatch_failed",
            },
        )
        == 1
    )


async def test_an_unknown_job_type_is_bounded_in_the_label(
    observability: ObservabilityHarness,
) -> None:
    repository = FakeOutboxRepository(jobs=[make_job("some.made.up.type")], pending={})
    publisher = make_publisher(repository, RecordingDispatcher())

    report = await publisher.publish_pending(limit=10)

    assert report.unknown_job_types == 1
    assert (
        observability.metrics.counter_value(
            MetricName.OUTBOX_PUBLISH_FAILURE_TOTAL,
            labels={
                LabelKey.JOB_TYPE: "unknown",
                LabelKey.ERROR_CODE: "unknown_job_type",
            },
        )
        == 1
    )
    label_values = {
        value for sample in observability.metrics.snapshot() for value in sample.labels.values()
    }
    assert "some.made.up.type" not in label_values


async def test_a_lost_publish_lease_is_counted_as_unconfirmed(
    observability: ObservabilityHarness,
) -> None:
    repository = FakeOutboxRepository(jobs=[make_job()], pending={}, publishable=False)
    publisher = make_publisher(repository, RecordingDispatcher())

    report = await publisher.publish_pending(limit=10)

    assert report.unconfirmed_publications == 1
    assert (
        observability.metrics.counter_value(
            MetricName.OUTBOX_PUBLISH_FAILURE_TOTAL,
            labels={
                LabelKey.JOB_TYPE: JobType.PROCESS_INGESTION_ITEM.value,
                LabelKey.ERROR_CODE: "other",
            },
        )
        == 1
    )


async def test_backlog_is_reported_as_a_gauge_per_known_job_type(
    observability: ObservabilityHarness,
) -> None:
    repository = FakeOutboxRepository(
        jobs=[],
        pending={JobType.PROCESS_INGESTION_ITEM.value: 42},
    )
    publisher = make_publisher(repository, RecordingDispatcher())

    backlog = await publisher.record_backlog()

    assert backlog[JobType.PROCESS_INGESTION_ITEM.value] == 42
    assert (
        observability.metrics.gauge_value(
            MetricName.OUTBOX_PENDING_JOBS,
            labels={LabelKey.JOB_TYPE: JobType.PROCESS_INGESTION_ITEM.value},
        )
        == 42
    )
    assert (
        observability.metrics.gauge_value(
            MetricName.OUTBOX_PENDING_JOBS,
            labels={LabelKey.JOB_TYPE: JobType.PROCESS_EMBEDDING.value},
        )
        == 0
    )
