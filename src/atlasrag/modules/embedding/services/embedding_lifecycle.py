import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from atlasrag.contracts.embedding import EmbeddingUnitOfWork
from atlasrag.contracts.error.embedding_errors import (
    ChunkSetChanged,
    EmbeddingRunAlreadyInFlight,
    IngestionItemNotEmbeddable,
)
from atlasrag.contracts.types.embedding import (
    ChunkVector,
    ClaimedEmbeddingRun,
    EmbeddableChunk,
    EmbeddingModelState,
    EmbeddingRunState,
)
from atlasrag.contracts.types.jobs import JobType
from atlasrag.modules.embedding.repositories import MAX_ATTEMPTS_EXCEEDED
from atlasrag.platform.configuration_hash import canonical_configuration_hash

SUPERSEDED_BY_RETRY = "superseded_by_retry"
INGESTION_ITEM_NOT_COMPLETED = "ingestion item is not completed"
CHUNK_SET_MOVED_DURING_RUN = "chunk set no longer matches the loaded chunk set"
INCOMPLETE_VECTOR_SET = "persisted vector count does not match the chunk count"


class EmbeddingLifecycleService:
    def __init__(
        self,
        uow_factory: Callable[[], EmbeddingUnitOfWork],
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
        ingestion_item_id: uuid.UUID,
        embedding_model_id: uuid.UUID,
        configuration: dict[str, object],
        created_by_principal_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        run_id = uuid.uuid4()
        async with self._uow_factory() as uow:
            if not await uow.chunks.is_item_embeddable(ingestion_item_id=ingestion_item_id):
                raise IngestionItemNotEmbeddable(reason=INGESTION_ITEM_NOT_COMPLETED)

            in_flight = await uow.runs.find_in_flight_run(
                ingestion_item_id=ingestion_item_id,
                embedding_model_id=embedding_model_id,
            )
            if in_flight is not None:
                raise EmbeddingRunAlreadyInFlight(
                    ingestion_item_id=str(ingestion_item_id),
                    embedding_model_id=str(embedding_model_id),
                )

            await uow.runs.add_run(
                run_id=run_id,
                ingestion_item_id=ingestion_item_id,
                embedding_model_id=embedding_model_id,
                configuration=configuration,
                configuration_hash=canonical_configuration_hash(configuration),
                created_by_principal_id=created_by_principal_id,
            )
            await uow.outbox.enqueue(
                job_id=uuid.uuid4(),
                job_type=JobType.PROCESS_EMBEDDING,
                aggregate_id=run_id,
                payload={"embedding_run_id": str(run_id)},
            )
            await uow.commit()
        return run_id

    async def find_run(self, *, run_id: uuid.UUID) -> EmbeddingRunState | None:
        async with self._uow_factory() as uow:
            return await uow.runs.find_run(run_id=run_id)

    async def find_model(self, *, model_id: uuid.UUID) -> EmbeddingModelState | None:
        async with self._uow_factory() as uow:
            return await uow.models.find_model(model_id=model_id)

    async def load_chunks(
        self,
        *,
        ingestion_item_id: uuid.UUID,
    ) -> tuple[EmbeddableChunk, ...]:
        async with self._uow_factory() as uow:
            if not await uow.chunks.is_item_embeddable(ingestion_item_id=ingestion_item_id):
                raise IngestionItemNotEmbeddable(reason=INGESTION_ITEM_NOT_COMPLETED)
            return await uow.chunks.list_chunks(ingestion_item_id=ingestion_item_id)

    async def claim(self, *, run_id: uuid.UUID) -> ClaimedEmbeddingRun | None:
        now = self._clock()
        async with self._uow_factory() as uow:
            claim = await uow.runs.claim_run(
                run_id=run_id,
                now=now,
                lease_expires_at=now + self._lease_duration,
                max_attempts=self._max_attempts,
            )
            if claim is not None:
                await uow.commit()
            return claim

    async def heartbeat(self, *, run_id: uuid.UUID, attempt_number: int) -> bool:
        now = self._clock()
        async with self._uow_factory() as uow:
            rowcount = await uow.runs.heartbeat(
                run_id=run_id,
                attempt_number=attempt_number,
                lease_expires_at=now + self._lease_duration,
            )
            if rowcount == 1:
                await uow.commit()
            return rowcount == 1

    async def schedule_retry(
        self,
        *,
        run_id: uuid.UUID,
        attempt_number: int,
        error_code: str,
        error_message: str | None = None,
    ) -> bool:
        async with self._uow_factory() as uow:
            if attempt_number >= self._max_attempts:
                rowcount = await uow.runs.mark_failed(
                    run_id=run_id,
                    attempt_number=attempt_number,
                    now=self._clock(),
                    error_code=MAX_ATTEMPTS_EXCEEDED,
                    error_message=error_message,
                    execution_metadata=None,
                )
            else:
                rowcount = await uow.runs.release_for_retry(
                    run_id=run_id,
                    attempt_number=attempt_number,
                    error_code=error_code,
                    error_message=error_message,
                )
                if rowcount == 1:
                    await uow.outbox.discard_pending_for_aggregate(
                        job_type=JobType.PROCESS_EMBEDDING,
                        aggregate_id=run_id,
                        failed_at=self._clock(),
                        failure_code=SUPERSEDED_BY_RETRY,
                    )
                    await uow.outbox.enqueue(
                        job_id=uuid.uuid4(),
                        job_type=JobType.PROCESS_EMBEDDING,
                        aggregate_id=run_id,
                        payload={"embedding_run_id": str(run_id)},
                    )
            if rowcount == 1:
                await uow.commit()
            return rowcount == 1

    async def mark_failed(
        self,
        *,
        run_id: uuid.UUID,
        attempt_number: int,
        error_code: str,
        error_message: str | None = None,
        execution_metadata: dict[str, object] | None = None,
    ) -> bool:
        async with self._uow_factory() as uow:
            rowcount = await uow.runs.mark_failed(
                run_id=run_id,
                attempt_number=attempt_number,
                now=self._clock(),
                error_code=error_code,
                error_message=error_message,
                execution_metadata=execution_metadata,
            )
            if rowcount == 1:
                await uow.commit()
            return rowcount == 1

    async def persist_vectors_and_mark_completed(
        self,
        *,
        run_id: uuid.UUID,
        attempt_number: int,
        ingestion_item_id: uuid.UUID,
        embedding_model_id: uuid.UUID,
        dimension: int,
        expected_chunk_ids: tuple[uuid.UUID, ...],
        vectors: tuple[ChunkVector, ...],
        execution_metadata: dict[str, object],
    ) -> bool:
        async with self._uow_factory() as uow:
            current_chunk_ids = await uow.chunks.list_chunk_ids(
                ingestion_item_id=ingestion_item_id
            )
            if current_chunk_ids != expected_chunk_ids:
                raise ChunkSetChanged(reason=CHUNK_SET_MOVED_DURING_RUN)

            await uow.embeddings.replace_for_model(
                embedding_model_id=embedding_model_id,
                embedding_run_id=run_id,
                dimension=dimension,
                chunk_ids=expected_chunk_ids,
                vectors=vectors,
            )
            persisted = await uow.embeddings.count_for_model(
                embedding_model_id=embedding_model_id,
                chunk_ids=expected_chunk_ids,
            )
            if persisted != len(expected_chunk_ids):
                raise ChunkSetChanged(reason=INCOMPLETE_VECTOR_SET)

            rowcount = await uow.runs.mark_completed(
                run_id=run_id,
                attempt_number=attempt_number,
                now=self._clock(),
                execution_metadata=execution_metadata,
            )
            if rowcount != 1:
                return False
            await uow.commit()
            return True

    async def reap_expired_runs(self) -> int:
        async with self._uow_factory() as uow:
            count = await uow.runs.fail_exhausted_expired_runs(
                now=self._clock(),
                max_attempts=self._max_attempts,
            )
            if count > 0:
                await uow.commit()
            return count


__all__ = [
    "CHUNK_SET_MOVED_DURING_RUN",
    "INCOMPLETE_VECTOR_SET",
    "INGESTION_ITEM_NOT_COMPLETED",
    "SUPERSEDED_BY_RETRY",
    "EmbeddingLifecycleService",
]
