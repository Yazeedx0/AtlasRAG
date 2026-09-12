import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.types.embedding import ClaimedEmbeddingRun
from atlasrag.modules.embedding.services.embedding_lifecycle import (
    EmbeddingLifecycleService,
)
from atlasrag.modules.embedding.workers.errors import (
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from atlasrag.modules.embedding.workers.heartbeat import EmbeddingLeaseHeartbeat
from atlasrag.modules.embedding.workers.job_handler import (
    TRANSIENT_EMBEDDING_ERROR,
    UNEXPECTED_EMBEDDING_ERROR,
    EmbeddingJobHandler,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
_HEARTBEAT_INTERVAL = timedelta(milliseconds=1)


class FakeLifecycle:
    def __init__(self, claims: list[ClaimedEmbeddingRun | None]) -> None:
        self._claims = claims
        self.heartbeat_results: list[bool] = []
        self.claim_calls: list[UUID] = []
        self.heartbeat_calls: list[tuple[UUID, int]] = []
        self.heartbeat_started = asyncio.Event()
        self.retry_calls: list[tuple[UUID, int, str]] = []
        self.failed_calls: list[tuple[UUID, int, str, str | None]] = []

    async def claim(self, *, run_id: UUID) -> ClaimedEmbeddingRun | None:
        self.claim_calls.append(run_id)
        return self._claims.pop(0)

    async def heartbeat(self, *, run_id: UUID, attempt_number: int) -> bool:
        self.heartbeat_calls.append((run_id, attempt_number))
        self.heartbeat_started.set()
        if self.heartbeat_results:
            return self.heartbeat_results.pop(0)
        return True

    async def schedule_retry(
        self,
        *,
        run_id: UUID,
        attempt_number: int,
        error_code: str,
        error_message: str | None = None,
    ) -> bool:
        assert error_message is None
        self.retry_calls.append((run_id, attempt_number, error_code))
        return True

    async def mark_failed(
        self,
        *,
        run_id: UUID,
        attempt_number: int,
        error_code: str,
        error_message: str | None = None,
        execution_metadata: dict[str, object] | None = None,
    ) -> bool:
        assert execution_metadata is None
        self.failed_calls.append((run_id, attempt_number, error_code, error_message))
        return True


class SuccessfulProcessor:
    def __init__(self) -> None:
        self.claims: list[ClaimedEmbeddingRun] = []

    async def process(self, *, claim: ClaimedEmbeddingRun) -> None:
        self.claims.append(claim)


class FailingProcessor:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def process(self, *, claim: ClaimedEmbeddingRun) -> None:
        raise self._error


class BlockingProcessor:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.finalized = False

    async def process(self, *, claim: ClaimedEmbeddingRun) -> None:
        await self.release.wait()
        self.finalized = True


def make_claim(run_id: UUID, *, attempt_number: int = 1) -> ClaimedEmbeddingRun:
    return ClaimedEmbeddingRun(
        embedding_run_id=run_id,
        ingestion_item_id=uuid4(),
        embedding_model_id=uuid4(),
        attempt_number=attempt_number,
        claimed_at=_NOW,
        lease_expires_at=_NOW + timedelta(minutes=2),
    )


def make_handler(lifecycle: FakeLifecycle, processor: object) -> EmbeddingJobHandler:
    service = cast(EmbeddingLifecycleService, lifecycle)
    return EmbeddingJobHandler(
        lifecycle=service,
        processor=processor,  # type: ignore[arg-type]
        heartbeat=EmbeddingLeaseHeartbeat(service, interval=_HEARTBEAT_INTERVAL),
    )


@pytest.mark.asyncio
async def test_unclaimable_run_is_skipped_without_processing() -> None:
    lifecycle = FakeLifecycle([None])
    processor = SuccessfulProcessor()

    await make_handler(lifecycle, processor).handle(embedding_run_id=uuid4())

    assert processor.claims == []
    assert lifecycle.retry_calls == []
    assert lifecycle.failed_calls == []


@pytest.mark.asyncio
async def test_duplicate_delivery_processes_the_run_once() -> None:
    run_id = uuid4()
    lifecycle = FakeLifecycle([make_claim(run_id), None])
    processor = SuccessfulProcessor()
    handler = make_handler(lifecycle, processor)

    await handler.handle(embedding_run_id=run_id)
    await handler.handle(embedding_run_id=run_id)

    assert len(processor.claims) == 1
    assert lifecycle.claim_calls == [run_id, run_id]


@pytest.mark.asyncio
async def test_permanent_failure_marks_the_run_failed() -> None:
    run_id = uuid4()
    lifecycle = FakeLifecycle([make_claim(run_id)])
    processor = FailingProcessor(
        PermanentEmbeddingError(error_code="embedding_vector_invalid")
    )

    await make_handler(lifecycle, processor).handle(embedding_run_id=run_id)

    assert lifecycle.failed_calls == [(run_id, 1, "embedding_vector_invalid", None)]
    assert lifecycle.retry_calls == []


@pytest.mark.asyncio
async def test_transient_failure_schedules_a_durable_retry() -> None:
    run_id = uuid4()
    lifecycle = FakeLifecycle([make_claim(run_id)])
    processor = FailingProcessor(TransientEmbeddingError("provider unavailable"))

    await make_handler(lifecycle, processor).handle(embedding_run_id=run_id)

    assert lifecycle.retry_calls == [(run_id, 1, TRANSIENT_EMBEDDING_ERROR)]
    assert lifecycle.failed_calls == []


@pytest.mark.asyncio
async def test_unexpected_failure_schedules_a_retry_without_leaking_the_message() -> None:
    run_id = uuid4()
    lifecycle = FakeLifecycle([make_claim(run_id)])
    processor = FailingProcessor(RuntimeError("secret-bearing detail"))

    await make_handler(lifecycle, processor).handle(embedding_run_id=run_id)

    assert lifecycle.retry_calls == [(run_id, 1, UNEXPECTED_EMBEDDING_ERROR)]


@pytest.mark.asyncio
async def test_lost_lease_stops_the_processor_and_leaves_the_run_untouched() -> None:
    run_id = uuid4()
    lifecycle = FakeLifecycle([make_claim(run_id)])
    lifecycle.heartbeat_results = [False]
    processor = BlockingProcessor()

    await make_handler(lifecycle, processor).handle(embedding_run_id=run_id)

    assert processor.finalized is False
    assert lifecycle.retry_calls == []
    assert lifecycle.failed_calls == []
