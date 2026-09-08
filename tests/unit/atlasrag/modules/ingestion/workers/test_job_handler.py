import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.types.ingestion import ClaimedIngestionItem
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.workers.errors import (
    PermanentIngestionError,
    TransientIngestionError,
)
from atlasrag.modules.ingestion.workers.heartbeat import LeaseHeartbeat
from atlasrag.modules.ingestion.workers.job_handler import (
    TRANSIENT_INGESTION_ERROR,
    UNEXPECTED_INGESTION_ERROR,
    IngestionJobHandler,
)

_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
_HEARTBEAT_INTERVAL = timedelta(milliseconds=1)


class FakeLifecycle:
    def __init__(self, claims: list[ClaimedIngestionItem | None]) -> None:
        self._claims = claims
        self.heartbeat_results: list[bool] = []
        self.operations: list[str] = []
        self.claim_calls: list[UUID] = []
        self.heartbeat_calls: list[tuple[UUID, int]] = []
        self.heartbeat_started = asyncio.Event()
        self.retry_calls: list[tuple[UUID, int, str]] = []
        self.failed_calls: list[tuple[UUID, int, str, str | None]] = []

    async def claim(self, *, item_id: UUID) -> ClaimedIngestionItem | None:
        self.operations.append("claim")
        self.claim_calls.append(item_id)
        return self._claims.pop(0)

    async def heartbeat(self, *, item_id: UUID, attempt_number: int) -> bool:
        self.operations.append("heartbeat")
        self.heartbeat_calls.append((item_id, attempt_number))
        self.heartbeat_started.set()
        if self.heartbeat_results:
            return self.heartbeat_results.pop(0)
        return True

    async def schedule_retry(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        error_code: str,
        error_message: str | None = None,
    ) -> bool:
        assert error_message is None
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
        assert execution_metadata is None
        self.failed_calls.append((item_id, attempt_number, error_code, error_message))
        return True


class SuccessfulProcessor:
    def __init__(self) -> None:
        self.claims: list[ClaimedIngestionItem] = []

    async def process(self, *, claim: ClaimedIngestionItem) -> None:
        self.claims.append(claim)


class FailingProcessor:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def process(self, *, claim: ClaimedIngestionItem) -> None:
        _ = claim
        raise self._error


class BlockingProcessor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.finalized = False

    async def process(self, *, claim: ClaimedIngestionItem) -> None:
        _ = claim
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        self.finalized = True


def make_claim(*, item_id: UUID | None = None, attempt_number: int = 1) -> ClaimedIngestionItem:
    return ClaimedIngestionItem(
        ingestion_item_id=item_id or uuid4(),
        document_artifact_id=uuid4(),
        attempt_number=attempt_number,
        claimed_at=_NOW,
        lease_expires_at=_NOW + timedelta(minutes=2),
    )


def make_handler(
    *,
    lifecycle: FakeLifecycle,
    processor: SuccessfulProcessor | FailingProcessor | BlockingProcessor,
) -> IngestionJobHandler:
    lifecycle_service = cast(IngestionLifecycleService, lifecycle)
    heartbeat = LeaseHeartbeat(
        lifecycle=lifecycle_service,
        interval=_HEARTBEAT_INTERVAL,
    )
    return IngestionJobHandler(
        lifecycle=lifecycle_service,
        processor=processor,
        heartbeat=heartbeat,
    )


@pytest.mark.asyncio
async def test_claimed_item_is_processed() -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    processor = SuccessfulProcessor()
    handler = make_handler(lifecycle=lifecycle, processor=processor)

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert processor.claims == [claim]


@pytest.mark.asyncio
async def test_unclaimable_item_is_not_processed() -> None:
    item_id = uuid4()
    lifecycle = FakeLifecycle([None])
    processor = SuccessfulProcessor()
    handler = make_handler(lifecycle=lifecycle, processor=processor)

    await handler.handle(ingestion_item_id=item_id)

    assert processor.claims == []


@pytest.mark.asyncio
async def test_duplicate_delivery_only_processes_the_claim_owner() -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim, None])
    processor = SuccessfulProcessor()
    handler = make_handler(lifecycle=lifecycle, processor=processor)

    await asyncio.gather(
        handler.handle(ingestion_item_id=claim.ingestion_item_id),
        handler.handle(ingestion_item_id=claim.ingestion_item_id),
    )

    assert processor.claims == [claim]


@pytest.mark.asyncio
async def test_heartbeat_renews_while_processor_is_running_and_stops_after_completion() -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    processor = BlockingProcessor()
    handler = make_handler(lifecycle=lifecycle, processor=processor)

    task = asyncio.create_task(handler.handle(ingestion_item_id=claim.ingestion_item_id))
    await asyncio.wait_for(processor.started.wait(), timeout=1)
    await asyncio.wait_for(lifecycle.heartbeat_started.wait(), timeout=1)
    processor.release.set()
    await asyncio.wait_for(task, timeout=1)
    heartbeat_count = len(lifecycle.heartbeat_calls)
    await asyncio.sleep(_HEARTBEAT_INTERVAL.total_seconds() * 3)

    assert heartbeat_count >= 1
    assert lifecycle.operations[:2] == ["claim", "heartbeat"]
    assert len(lifecycle.heartbeat_calls) == heartbeat_count
    assert processor.finalized is True


@pytest.mark.asyncio
async def test_lost_lease_cancels_processor_before_it_can_finalize() -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    lifecycle.heartbeat_results = [False]
    processor = BlockingProcessor()
    handler = make_handler(lifecycle=lifecycle, processor=processor)

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert processor.cancelled.is_set()
    assert processor.finalized is False
    assert lifecycle.retry_calls == []
    assert lifecycle.failed_calls == []


@pytest.mark.asyncio
async def test_transient_processor_error_schedules_a_durable_retry() -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(
        lifecycle=lifecycle,
        processor=FailingProcessor(TransientIngestionError("provider unavailable")),
    )

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert lifecycle.retry_calls == [
        (claim.ingestion_item_id, claim.attempt_number, TRANSIENT_INGESTION_ERROR)
    ]
    assert lifecycle.failed_calls == []


@pytest.mark.asyncio
async def test_permanent_processor_error_marks_the_item_failed() -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(
        lifecycle=lifecycle,
        processor=FailingProcessor(
            PermanentIngestionError(
                error_code="unsupported_artifact",
                message="Unsupported artifact type.",
            )
        ),
    )

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert lifecycle.failed_calls == [
        (
            claim.ingestion_item_id,
            claim.attempt_number,
            "unsupported_artifact",
            "Unsupported artifact type.",
        )
    ]
    assert lifecycle.retry_calls == []


@pytest.mark.asyncio
async def test_unexpected_processor_error_is_retried_without_persisting_its_message() -> None:
    claim = make_claim()
    lifecycle = FakeLifecycle([claim])
    handler = make_handler(
        lifecycle=lifecycle,
        processor=FailingProcessor(RuntimeError("contains a secret-like value")),
    )

    await handler.handle(ingestion_item_id=claim.ingestion_item_id)

    assert lifecycle.retry_calls == [
        (claim.ingestion_item_id, claim.attempt_number, UNEXPECTED_INGESTION_ERROR)
    ]
