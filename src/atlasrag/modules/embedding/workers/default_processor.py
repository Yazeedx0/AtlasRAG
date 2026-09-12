from collections.abc import Callable
from uuid import UUID

from atlasrag.contracts.embedding import EmbeddingProvider
from atlasrag.contracts.error.embedding_errors import (
    ChunkSetChanged,
    EmbeddingInputInvalid,
    EmbeddingInputTooLarge,
    EmbeddingProviderPermanentError,
    EmbeddingProviderTransientError,
    EmbeddingVectorInvalid,
    IngestionItemNotEmbeddable,
    InvalidEmbeddingResponse,
)
from atlasrag.contracts.types.embedding import (
    ClaimedEmbeddingRun,
    EmbeddableChunk,
    EmbeddingModelState,
    EmbeddingRunState,
)
from atlasrag.modules.embedding.batching import EmbeddingBatcher, EmbeddingBatchOutcome
from atlasrag.modules.embedding.config import EmbeddingRunConfig
from atlasrag.modules.embedding.services.embedding_lifecycle import (
    EmbeddingLifecycleService,
)
from atlasrag.modules.embedding.workers.errors import (
    EmbeddingLeaseLost,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)

EMBEDDING_RUN_MISSING = "embedding_run_missing"
EMBEDDING_MODEL_MISSING = "embedding_model_missing"
EMBEDDING_CONFIGURATION_INVALID = "embedding_configuration_invalid"
INGESTION_ITEM_NOT_EMBEDDABLE = "ingestion_item_not_embeddable"
EMBEDDING_INPUT_TOO_LARGE = "embedding_input_too_large"
EMBEDDING_INPUT_INVALID = "embedding_input_invalid"
EMBEDDING_VECTOR_INVALID = "embedding_vector_invalid"
EMBEDDING_PROVIDER_FAILED = "embedding_provider_failed"
INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
CHUNK_SET_CHANGED = "chunk_set_changed"
NO_CHUNKS_TO_EMBED = "no_chunks_to_embed"

ProviderFactory = Callable[[EmbeddingModelState], EmbeddingProvider]


def build_execution_metadata(
    *,
    model: EmbeddingModelState,
    config: EmbeddingRunConfig,
    outcome: EmbeddingBatchOutcome,
    chunk_count: int,
) -> dict[str, object]:
    return {
        "embedding": {
            "provider": model.provider.value,
            "model": model.model_name,
            "model_revision": model.model_revision,
            "dimension": model.dimension,
            "distance_metric": model.distance_metric.value,
            "batch_count": outcome.batch_count,
            "request_count": outcome.request_count,
            "embedded_chunk_count": chunk_count,
            "input_tokens": outcome.usage.input_tokens,
            "total_tokens": outcome.usage.total_tokens,
            "batch_size": config.batch_size,
            "max_batch_tokens": config.max_batch_tokens,
            "concurrency": config.concurrency,
        }
    }


class DefaultEmbeddingProcessor:
    def __init__(
        self,
        *,
        lifecycle: EmbeddingLifecycleService,
        provider_factory: ProviderFactory,
    ) -> None:
        self._lifecycle = lifecycle
        self._provider_factory = provider_factory

    async def process(self, *, claim: ClaimedEmbeddingRun) -> None:
        run = await self._load_run(run_id=claim.embedding_run_id)
        model = await self._load_model(model_id=claim.embedding_model_id)
        config = self._load_config(run=run)
        chunks = await self._load_chunks(ingestion_item_id=claim.ingestion_item_id)

        outcome = await self._embed(chunks=chunks, model=model, config=config)
        completed = await self._persist(
            claim=claim,
            model=model,
            config=config,
            chunks=chunks,
            outcome=outcome,
        )
        if not completed:
            raise EmbeddingLeaseLost("Embedding lease was lost before completion.")

    async def _load_run(self, *, run_id: UUID) -> EmbeddingRunState:
        run = await self._lifecycle.find_run(run_id=run_id)
        if run is None:
            raise PermanentEmbeddingError(error_code=EMBEDDING_RUN_MISSING)
        return run

    async def _load_model(self, *, model_id: UUID) -> EmbeddingModelState:
        model = await self._lifecycle.find_model(model_id=model_id)
        if model is None:
            raise PermanentEmbeddingError(error_code=EMBEDDING_MODEL_MISSING)
        return model

    def _load_config(self, *, run: EmbeddingRunState) -> EmbeddingRunConfig:
        try:
            return EmbeddingRunConfig.from_run_configuration(run.configuration)
        except ValueError as error:
            raise PermanentEmbeddingError(
                error_code=EMBEDDING_CONFIGURATION_INVALID,
            ) from error

    async def _load_chunks(self, *, ingestion_item_id: UUID) -> tuple[EmbeddableChunk, ...]:
        try:
            chunks = await self._lifecycle.load_chunks(ingestion_item_id=ingestion_item_id)
        except IngestionItemNotEmbeddable as error:
            raise PermanentEmbeddingError(error_code=INGESTION_ITEM_NOT_EMBEDDABLE) from error
        if not chunks:
            raise PermanentEmbeddingError(error_code=NO_CHUNKS_TO_EMBED)
        return chunks

    async def _embed(
        self,
        *,
        chunks: tuple[EmbeddableChunk, ...],
        model: EmbeddingModelState,
        config: EmbeddingRunConfig,
    ) -> EmbeddingBatchOutcome:
        batcher = EmbeddingBatcher(
            provider=self._provider_factory(model),
            model=model,
            config=config,
        )
        try:
            return await batcher.embed(chunks=chunks)
        except EmbeddingInputTooLarge as error:
            raise PermanentEmbeddingError(error_code=EMBEDDING_INPUT_TOO_LARGE) from error
        except EmbeddingInputInvalid as error:
            raise PermanentEmbeddingError(error_code=EMBEDDING_INPUT_INVALID) from error
        except EmbeddingVectorInvalid as error:
            raise PermanentEmbeddingError(error_code=EMBEDDING_VECTOR_INVALID) from error
        except InvalidEmbeddingResponse as error:
            raise PermanentEmbeddingError(error_code=INVALID_PROVIDER_RESPONSE) from error
        except EmbeddingProviderPermanentError as error:
            raise PermanentEmbeddingError(error_code=EMBEDDING_PROVIDER_FAILED) from error
        except EmbeddingProviderTransientError as error:
            raise TransientEmbeddingError("Embedding provider is unavailable.") from error

    async def _persist(
        self,
        *,
        claim: ClaimedEmbeddingRun,
        model: EmbeddingModelState,
        config: EmbeddingRunConfig,
        chunks: tuple[EmbeddableChunk, ...],
        outcome: EmbeddingBatchOutcome,
    ) -> bool:
        try:
            return await self._lifecycle.persist_vectors_and_mark_completed(
                run_id=claim.embedding_run_id,
                attempt_number=claim.attempt_number,
                ingestion_item_id=claim.ingestion_item_id,
                embedding_model_id=claim.embedding_model_id,
                dimension=model.dimension,
                expected_chunk_ids=tuple(chunk.chunk_id for chunk in chunks),
                vectors=outcome.vectors,
                execution_metadata=build_execution_metadata(
                    model=model,
                    config=config,
                    outcome=outcome,
                    chunk_count=len(chunks),
                ),
            )
        except ChunkSetChanged as error:
            raise PermanentEmbeddingError(error_code=CHUNK_SET_CHANGED) from error


__all__ = [
    "CHUNK_SET_CHANGED",
    "EMBEDDING_CONFIGURATION_INVALID",
    "EMBEDDING_INPUT_INVALID",
    "EMBEDDING_INPUT_TOO_LARGE",
    "EMBEDDING_MODEL_MISSING",
    "EMBEDDING_PROVIDER_FAILED",
    "EMBEDDING_RUN_MISSING",
    "EMBEDDING_VECTOR_INVALID",
    "INGESTION_ITEM_NOT_EMBEDDABLE",
    "INVALID_PROVIDER_RESPONSE",
    "NO_CHUNKS_TO_EMBED",
    "DefaultEmbeddingProcessor",
    "ProviderFactory",
    "build_execution_metadata",
]
