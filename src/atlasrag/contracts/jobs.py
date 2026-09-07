from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from atlasrag.contracts.types.jobs import ClaimedOutboxJob, DeadLetteredJob, JobType


class JobOutboxRepository(Protocol):
    async def enqueue(
        self,
        *,
        job_id: UUID,
        job_type: JobType,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None:
        ...

    async def discard_pending_for_aggregate(
        self,
        *,
        job_type: JobType,
        aggregate_id: UUID,
        failed_at: datetime,
        failure_code: str,
    ) -> int:
        ...

    async def claim_unpublished_batch(
        self,
        *,
        limit: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> tuple[ClaimedOutboxJob, ...]:
        ...

    async def mark_published(
        self,
        *,
        job_id: UUID,
        attempt_number: int,
        published_at: datetime,
    ) -> bool:
        ...

    async def release_publish_claim(
        self,
        *,
        job_id: UUID,
        attempt_number: int,
        error_code: str,
        next_attempt_at: datetime,
    ) -> bool:
        ...

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        attempt_number: int,
        failed_at: datetime,
        failure_code: str,
        last_error: str | None = None,
    ) -> bool:
        ...

    async def count_pending(self) -> int:
        ...

    async def count_dead_lettered(self) -> int:
        ...

    async def find_dead_lettered(self, *, limit: int) -> tuple[DeadLetteredJob, ...]:
        ...


class JobOutboxUnitOfWork(Protocol):
    outbox: JobOutboxRepository

    async def __aenter__(self) -> "JobOutboxUnitOfWork":
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        ...

    async def commit(self) -> None:
        ...


__all__ = ["JobOutboxRepository", "JobOutboxUnitOfWork"]
