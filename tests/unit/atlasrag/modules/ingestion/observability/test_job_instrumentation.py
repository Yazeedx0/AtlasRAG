import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from tests.unit.conftest import ObservabilityHarness

from atlasrag.contracts.types.ingestion import ClaimedIngestionItem
from atlasrag.contracts.types.observability import (
    JobStage,
    LabelKey,
    MetricName,
    SpanName,
)
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.workers.errors import (
    IngestionLeaseLost,
    PermanentIngestionError,
    TransientIngestionError,
)
from atlasrag.modules.ingestion.workers.heartbeat import LeaseHeartbeat
from atlasrag.modules.ingestion.workers.job_handler import (
    TRANSIENT_INGESTION_ERROR,
    UNEXPECTED_INGESTION_ERROR,
    IngestionJobHandler,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
_HEARTBEAT_INTERVAL = timedelta(milliseconds=1)
_JOB_TYPE = "ingestion.process"


class FakeLifecycle:
    def __init__(self, claims: list[ClaimedIngestionItem | None]) -> None:
        self._claims = claims
        self.heartbeat_results: list[bool] = []
        self.retry_calls: list[tuple[UUID, int, str]] = []
        self.failed_calls: list[tuple[UUID, int, str]] = []

    async def claim(self, *, item_id: UUID) -> ClaimedIngestionItem | None:
        return self._claims.pop(0) if self._claims else None

    async def heartbeat(self, *, item_id: UUID, attempt_number: int) -> bool:
        if self.heartbeat_results:
            return self.heartbeat_results.pop(0)
        await asyncio.sleep(0.5)
        return True

    async def schedule_retry(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        error_code: str,
        error_message: str | None = None,
    ) -> bool:
        self.retry_calls.append((item_id, attempt_number, error_code))
        return True

    async def mark_failed(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        error_code: str,
        error_message: str | None = None,
        execution_metadata: dict[str, object] | None = None,
    ) -> bool:
        self.failed_calls.append((item_id, attempt_number, error_code))
        return True


class SuccessfulProcessor:
    async def process(self, *, claim: ClaimedIngestionItem) -> None:
        return None


class FailingProcessor:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def process(self, *, claim: ClaimedIngestionItem) -> None:
        raise self._error


class StageFailingProcessor:
    def __init__(self, *, stage: JobStage, span: SpanName, error: Exception) -> None:
        self._stage = stage
        self._span = span
        self._error = error

    async def process(self, *, claim: ClaimedIngestionItem) -> None:
        from atlasrag.platform.observability import traced_stage

        async with traced_stage(self._span, stage=self._stage):
            raise self._error


def make_claim(attempt_number: int = 1) -> ClaimedIngestionItem:
    return ClaimedIngestionItem(
        ingestion_item_id=uuid4(),
        document_artifact_id=uuid4(),
        attempt_number=attempt_number,
        claimed_at=_NOW,
        lease_expires_at=_NOW + timedelta(seconds=60),
    )


def make_handler(
    *,
    lifecycle: FakeLifecycle,
    processor: object,
) -> IngestionJobHandler:
    typed_lifecycle = cast(IngestionLifecycleService, lifecycle)
    return IngestionJobHandler(
        lifecycle=typed_lifecycle,
        processor=processor,  # type: ignore[arg-type]
        heartbeat=LeaseHeartbeat(typed_lifecycle, interval=_HEARTBEAT_INTERVAL),
    )


async def test_a_successful_job_emits_the_job_and_claim_spans(
    observability: ObservabilityHarness,
) -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(lifecycle=lifecycle, processor=SuccessfulProcessor())

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert SpanName.INGESTION_JOB.value in observability.span_names()
    assert SpanName.INGESTION_CLAIM.value in observability.span_names()
    job_span = observability.tracer.find(SpanName.INGESTION_JOB)[0]
    assert job_span.attributes["claimed"] is True
    assert job_span.attributes["attempt_number"] == 1


async def test_a_successful_job_increments_started_and_duration(
    observability: ObservabilityHarness,
) -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(lifecycle=lifecycle, processor=SuccessfulProcessor())

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_JOBS_STARTED_TOTAL,
            labels={LabelKey.JOB_TYPE: _JOB_TYPE},
        )
        == 1
    )
    assert (
        observability.metrics.histogram_count(
            MetricName.INGESTION_DURATION_SECONDS,
            labels={
                LabelKey.JOB_TYPE: _JOB_TYPE,
                LabelKey.LANGUAGE: "unknown",
                LabelKey.STATUS: "success",
            },
        )
        == 1
    )


async def test_an_unclaimable_item_does_not_count_as_a_started_job(
    observability: ObservabilityHarness,
) -> None:
    lifecycle = FakeLifecycle([None])
    handler = make_handler(lifecycle=lifecycle, processor=SuccessfulProcessor())

    await handler.handle(ingestion_item_id=uuid4())

    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_JOBS_STARTED_TOTAL,
            labels={LabelKey.JOB_TYPE: _JOB_TYPE},
        )
        == 0
    )
    job_span = observability.tracer.find(SpanName.INGESTION_JOB)[0]
    assert job_span.attributes["claimed"] is False


async def test_a_permanent_failure_increments_failed_with_its_stage_and_category(
    observability: ObservabilityHarness,
) -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(
        lifecycle=lifecycle,
        processor=StageFailingProcessor(
            stage=JobStage.ARTIFACT_INTEGRITY,
            span=SpanName.ARTIFACT_INTEGRITY,
            error=PermanentIngestionError(error_code="artifact_integrity_mismatch"),
        ),
    )

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_JOBS_FAILED_TOTAL,
            labels={
                LabelKey.JOB_TYPE: _JOB_TYPE,
                LabelKey.LANGUAGE: "unknown",
                LabelKey.STAGE: JobStage.ARTIFACT_INTEGRITY.value,
                LabelKey.ERROR_CODE: "artifact_integrity",
            },
        )
        == 1
    )
    assert lifecycle.failed_calls == [(claim.ingestion_item_id, 1, "artifact_integrity_mismatch")]


async def test_a_transient_failure_increments_retries(
    observability: ObservabilityHarness,
) -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(
        lifecycle=lifecycle,
        processor=StageFailingProcessor(
            stage=JobStage.EXTRACTION,
            span=SpanName.EXTRACTION,
            error=TransientIngestionError("provider unavailable"),
        ),
    )

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_RETRIES_TOTAL,
            labels={
                LabelKey.JOB_TYPE: _JOB_TYPE,
                LabelKey.STAGE: JobStage.EXTRACTION.value,
                LabelKey.ERROR_CODE: "transient",
            },
        )
        == 1
    )
    assert lifecycle.retry_calls == [(claim.ingestion_item_id, 1, TRANSIENT_INGESTION_ERROR)]


async def test_an_unexpected_failure_is_retried_under_a_bounded_error_code(
    observability: ObservabilityHarness,
) -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(
        lifecycle=lifecycle,
        processor=FailingProcessor(RuntimeError("connection to 10.0.0.7 refused")),
    )

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_RETRIES_TOTAL,
            labels={
                LabelKey.JOB_TYPE: _JOB_TYPE,
                LabelKey.STAGE: JobStage.UNKNOWN.value,
                LabelKey.ERROR_CODE: "other",
            },
        )
        == 1
    )
    assert lifecycle.retry_calls == [(claim.ingestion_item_id, 1, UNEXPECTED_INGESTION_ERROR)]
    label_keys = observability.metrics.label_keys(MetricName.INGESTION_RETRIES_TOTAL)
    assert "10.0.0.7" not in "".join(label_keys)


async def test_a_lost_lease_increments_the_lease_lost_counter(
    observability: ObservabilityHarness,
) -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(
        lifecycle=lifecycle,
        processor=FailingProcessor(IngestionLeaseLost("lease gone")),
    )

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_LEASE_LOST_TOTAL,
            labels={LabelKey.JOB_TYPE: _JOB_TYPE, LabelKey.STAGE: JobStage.UNKNOWN.value},
        )
        == 1
    )
    assert lifecycle.retry_calls == []
    assert lifecycle.failed_calls == []


async def test_a_heartbeat_lease_loss_is_counted_and_does_not_mark_the_item(
    observability: ObservabilityHarness,
) -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    lifecycle.heartbeat_results = [False]

    class BlockingProcessor:
        async def process(self, *, claim: ClaimedIngestionItem) -> None:
            await asyncio.sleep(5)

    handler = make_handler(lifecycle=lifecycle, processor=BlockingProcessor())

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_LEASE_LOST_TOTAL,
            labels={LabelKey.JOB_TYPE: _JOB_TYPE, LabelKey.STAGE: JobStage.UNKNOWN.value},
        )
        == 1
    )
    assert lifecycle.failed_calls == []


async def test_metric_labels_never_carry_job_identifiers(
    observability: ObservabilityHarness,
) -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(lifecycle=lifecycle, processor=SuccessfulProcessor())

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    recorded = observability.metrics.snapshot()
    assert recorded
    for sample in recorded:
        serialized = "".join(f"{key}{value}" for key, value in sample.labels.items())
        assert str(claim.ingestion_item_id) not in serialized
        assert str(claim.document_artifact_id) not in serialized
