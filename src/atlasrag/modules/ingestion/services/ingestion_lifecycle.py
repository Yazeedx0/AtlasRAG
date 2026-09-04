import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from atlasrag.contracts.ingestion import IngestionUnitOfWork
from atlasrag.contracts.types.ingestion import (
    ClaimedIngestionItem,
    IngestionItemState,
    IngestionRunState,
)
from atlasrag.contracts.types.jobs import JobType
from atlasrag.modules.ingestion.repositories import MAX_ATTEMPTS_EXCEEDED


class IngestionLifecycleService:
    def __init__(
        self,
        uow_factory: Callable[[], IngestionUnitOfWork],
        *,
        lease_duration: timedelta,
        max_attempts: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._uow_factory = uow_factory
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
        async with self._uow_factory() as uow:
            await uow.ingestion.add_run(
                run_id=run_id,
                configuration=configuration,
                configuration_hash=configuration_hash,
                created_by_principal_id=created_by_principal_id,
            )
            await uow.commit()
        return run_id

    async def add_item(
        self,
        *,
        ingestion_run_id: uuid.UUID,
        document_artifact_id: uuid.UUID,
    ) -> uuid.UUID:
        item_id = uuid.uuid4()
        async with self._uow_factory() as uow:
            await uow.ingestion.add_item(
                item_id=item_id,
                ingestion_run_id=ingestion_run_id,
                document_artifact_id=document_artifact_id,
            )
            await uow.outbox.enqueue(
                job_id=uuid.uuid4(),
                job_type=JobType.PROCESS_INGESTION_ITEM,
                aggregate_id=item_id,
                payload={"ingestion_item_id": str(item_id)},
            )
            await uow.commit()
        return item_id

    async def find_run(self, *, run_id: uuid.UUID) -> IngestionRunState | None:
        async with self._uow_factory() as uow:
            return await uow.ingestion.find_run(run_id=run_id)

    async def find_item(self, *, item_id: uuid.UUID) -> IngestionItemState | None:
        async with self._uow_factory() as uow:
            return await uow.ingestion.find_item(item_id=item_id)

    async def claim(self, *, item_id: uuid.UUID) -> ClaimedIngestionItem | None:
        now = self._clock()
        async with self._uow_factory() as uow:
            claim = await uow.ingestion.claim_item(
                item_id=item_id,
                now=now,
                lease_expires_at=now + self._lease_duration,
                max_attempts=self._max_attempts,
            )
            if claim is not None:
                await uow.commit()
            return claim

    async def heartbeat(
        self,
        *,
        item_id: uuid.UUID,
        attempt_number: int,
    ) -> bool:
        now = self._clock()
        async with self._uow_factory() as uow:
            rowcount = await uow.ingestion.heartbeat(
                item_id=item_id,
                attempt_number=attempt_number,
                lease_expires_at=now + self._lease_duration,
            )
            if rowcount == 1:
                await uow.commit()
            return rowcount == 1

    async def release_for_retry(
        self,
        *,
        item_id: uuid.UUID,
        attempt_number: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        async with self._uow_factory() as uow:
            if attempt_number >= self._max_attempts:
                rowcount = await uow.ingestion.mark_failed(
                    item_id=item_id,
                    attempt_number=attempt_number,
                    now=self._clock(),
                    error_code=MAX_ATTEMPTS_EXCEEDED,
                    error_message=error_message,
                    execution_metadata=None,
                )
            else:
                rowcount = await uow.ingestion.release_for_retry(
                    item_id=item_id,
                    attempt_number=attempt_number,
                    error_code=error_code,
                    error_message=error_message,
                )
            if rowcount == 1:
                await uow.commit()
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
        async with self._uow_factory() as uow:
            rowcount = await uow.ingestion.mark_failed(
                item_id=item_id,
                attempt_number=attempt_number,
                now=self._clock(),
                error_code=error_code,
                error_message=error_message,
                execution_metadata=execution_metadata,
            )
            if rowcount == 1:
                await uow.commit()
            return rowcount == 1

    async def reap_expired_items(self) -> int:
        async with self._uow_factory() as uow:
            count = await uow.ingestion.fail_exhausted_expired_items(
                now=self._clock(),
                max_attempts=self._max_attempts,
            )
            if count > 0:
                await uow.commit()
            return count
