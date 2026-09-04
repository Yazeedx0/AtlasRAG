from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from atlasrag.contracts.jobs import JobOutboxRepository
from atlasrag.contracts.types.ingestion import (
    ClaimedIngestionItem,
    IngestionItemState,
    IngestionRunState,
)


class IngestionLifecycleRepository(Protocol):
    async def add_run(
        self,
        *,
        run_id: UUID,
        configuration: dict[str, object],
        configuration_hash: str,
        created_by_principal_id: UUID | None,
    ) -> None:
        ...

    async def add_item(
        self,
        *,
        item_id: UUID,
        ingestion_run_id: UUID,
        document_artifact_id: UUID,
    ) -> None:
        ...

    async def find_run(self, *, run_id: UUID) -> IngestionRunState | None:
        ...

    async def find_item(self, *, item_id: UUID) -> IngestionItemState | None:
        ...

    async def claim_item(
        self,
        *,
        item_id: UUID,
        now: datetime,
        lease_expires_at: datetime,
        max_attempts: int,
    ) -> ClaimedIngestionItem | None:
        ...

    async def heartbeat(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        lease_expires_at: datetime,
    ) -> int:
        ...

    async def release_for_retry(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        error_code: str | None,
        error_message: str | None,
    ) -> int:
        ...

    async def mark_failed(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        now: datetime,
        error_code: str,
        error_message: str | None,
        execution_metadata: dict[str, object] | None,
    ) -> int:
        ...

    async def fail_exhausted_expired_items(
        self,
        *,
        now: datetime,
        max_attempts: int,
    ) -> int:
        ...


class IngestionUnitOfWork(Protocol):
    ingestion: IngestionLifecycleRepository
    outbox: JobOutboxRepository

    async def __aenter__(self) -> "IngestionUnitOfWork":
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


__all__ = ["IngestionLifecycleRepository", "IngestionUnitOfWork"]
