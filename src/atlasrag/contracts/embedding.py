from datetime import datetime
from types import TracebackType
from typing import Protocol, runtime_checkable
from uuid import UUID

from atlasrag.contracts.jobs import JobOutboxRepository
from atlasrag.contracts.types.embedding import (
    ChunkVector,
    ClaimedEmbeddingRun,
    EmbeddableChunk,
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingModelIdentity,
    EmbeddingModelState,
    EmbeddingRunState,
)


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed(self, *, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        ...


class EmbeddingModelRepository(Protocol):
    async def add_model(
        self,
        *,
        model_id: UUID,
        identity: EmbeddingModelIdentity,
        configuration_hash: str,
    ) -> None:
        ...

    async def find_model(self, *, model_id: UUID) -> EmbeddingModelState | None:
        ...

    async def find_model_by_identity(
        self,
        *,
        provider: str,
        model_name: str,
        model_revision: str,
        configuration_hash: str,
    ) -> EmbeddingModelState | None:
        ...


class EmbeddingRunRepository(Protocol):
    async def add_run(
        self,
        *,
        run_id: UUID,
        ingestion_item_id: UUID,
        embedding_model_id: UUID,
        configuration: dict[str, object],
        configuration_hash: str,
        created_by_principal_id: UUID | None,
    ) -> None:
        ...

    async def find_run(self, *, run_id: UUID) -> EmbeddingRunState | None:
        ...

    async def find_in_flight_run(
        self,
        *,
        ingestion_item_id: UUID,
        embedding_model_id: UUID,
    ) -> EmbeddingRunState | None:
        ...

    async def claim_run(
        self,
        *,
        run_id: UUID,
        now: datetime,
        lease_expires_at: datetime,
        max_attempts: int,
    ) -> ClaimedEmbeddingRun | None:
        ...

    async def heartbeat(
        self,
        *,
        run_id: UUID,
        attempt_number: int,
        lease_expires_at: datetime,
    ) -> int:
        ...

    async def release_for_retry(
        self,
        *,
        run_id: UUID,
        attempt_number: int,
        error_code: str | None,
        error_message: str | None,
    ) -> int:
        ...

    async def mark_failed(
        self,
        *,
        run_id: UUID,
        attempt_number: int,
        now: datetime,
        error_code: str,
        error_message: str | None,
        execution_metadata: dict[str, object] | None,
    ) -> int:
        ...

    async def mark_completed(
        self,
        *,
        run_id: UUID,
        attempt_number: int,
        now: datetime,
        execution_metadata: dict[str, object],
    ) -> int:
        ...

    async def fail_exhausted_expired_runs(
        self,
        *,
        now: datetime,
        max_attempts: int,
    ) -> int:
        ...


class ChunkEmbeddingRepository(Protocol):
    async def replace_for_model(
        self,
        *,
        embedding_model_id: UUID,
        embedding_run_id: UUID,
        dimension: int,
        chunk_ids: tuple[UUID, ...],
        vectors: tuple[ChunkVector, ...],
    ) -> None:
        ...

    async def count_for_model(
        self,
        *,
        embedding_model_id: UUID,
        chunk_ids: tuple[UUID, ...],
    ) -> int:
        ...


class EmbeddingChunkSourceRepository(Protocol):
    async def is_item_embeddable(self, *, ingestion_item_id: UUID) -> bool:
        ...

    async def list_chunks(self, *, ingestion_item_id: UUID) -> tuple[EmbeddableChunk, ...]:
        ...

    async def list_chunk_ids(self, *, ingestion_item_id: UUID) -> tuple[UUID, ...]:
        ...


class EmbeddingUnitOfWork(Protocol):
    models: EmbeddingModelRepository
    runs: EmbeddingRunRepository
    embeddings: ChunkEmbeddingRepository
    chunks: EmbeddingChunkSourceRepository
    outbox: JobOutboxRepository

    async def __aenter__(self) -> "EmbeddingUnitOfWork":
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


__all__ = [
    "ChunkEmbeddingRepository",
    "EmbeddingChunkSourceRepository",
    "EmbeddingModelRepository",
    "EmbeddingProvider",
    "EmbeddingRunRepository",
    "EmbeddingUnitOfWork",
]
