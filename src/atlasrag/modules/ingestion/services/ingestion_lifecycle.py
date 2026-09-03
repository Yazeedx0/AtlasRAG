import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from atlasrag.contracts.types.ingestion import (
    ClaimedIngestionItem,
    IngestionItemState,
    IngestionRunState,
)
from atlasrag.modules.ingestion.repositories import (
    MAX_ATTEMPTS_EXCEEDED,
    IngestionRepository,
)


class IngestionLifecycleService:
    def __init__(
        self,
        repository: IngestionRepository,
        *,
        lease_duration: timedelta,
        max_attempts: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._lease_duration = lease_duration
        self._max_attempts = max_attempts
        self._clock = clock

    async def create_run(
        self,
        *,
        configuration: dict[str, object],
        configuration_hash: str,
        created_by_principal_id: uuid.UUID | None,
    ) -> uuid.UUID:
        run_id = uuid.uuid4()
        await self._repository.add_run(
            run_id=run_id,
            configuration=configuration,
            configuration_hash=configuration_hash,
            created_by_principal_id=created_by_principal_id,
        )
        return run_id

    async def add_item(
        self,
        *,
        ingestion_run_id: uuid.UUID,
        document_artifact_id: uuid.UUID,
    ) -> uuid.UUID:
        item_id = uuid.uuid4()
        await self._repository.add_item(
            item_id=item_id,
            ingestion_run_id=ingestion_run_id,
            document_artifact_id=document_artifact_id,
        )
        return item_id

    async def find_run(self, *, run_id: uuid.UUID) -> IngestionRunState | None:
        return await self._repository.find_run(run_id=run_id)

    async def find_item(self, *, item_id: uuid.UUID) -> IngestionItemState | None:
        return await self._repository.find_item(item_id=item_id)

    async def claim(self, *, item_id: uuid.UUID) -> ClaimedIngestionItem | None:
        now = self._clock()
        return await self._repository.claim_item(
            item_id=item_id,
            now=now,
            lease_expires_at=now + self._lease_duration,
            max_attempts=self._max_attempts,
        )

    async def heartbeat(
        self,
        *,
        item_id: uuid.UUID,
        attempt_number: int,
    ) -> bool:
        now = self._clock()
        rowcount = await self._repository.heartbeat(
            item_id=item_id,
            attempt_number=attempt_number,
            lease_expires_at=now + self._lease_duration,
        )
        return rowcount == 1

    async def release_for_retry(
        self,
        *,
        item_id: uuid.UUID,
        attempt_number: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        if attempt_number >= self._max_attempts:
            return await self.mark_failed(
                item_id=item_id,
                attempt_number=attempt_number,
                error_code=MAX_ATTEMPTS_EXCEEDED,
                error_message=error_message,
            )

        rowcount = await self._repository.release_for_retry(
            item_id=item_id,
            attempt_number=attempt_number,
            error_code=error_code,
            error_message=error_message,
        )
        return rowcount == 1

    async def mark_failed(
        self,
        *,
        item_id: uuid.UUID,
        attempt_number: int,
        error_code: str,
        error_message: str | None = None,
        execution_metadata: dict[str, object] | None = None,
    ) -> bool:
        rowcount = await self._repository.mark_failed(
            item_id=item_id,
            attempt_number=attempt_number,
            now=self._clock(),
            error_code=error_code,
            error_message=error_message,
            execution_metadata=execution_metadata,
        )
        return rowcount == 1

    async def reap_expired_items(self) -> int:
        return await self._repository.fail_exhausted_expired_items(
            now=self._clock(),
            max_attempts=self._max_attempts,
        )
