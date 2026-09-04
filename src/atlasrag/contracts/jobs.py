from typing import Protocol
from uuid import UUID

from atlasrag.contracts.types.jobs import JobType


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


__all__ = ["JobOutboxRepository"]
