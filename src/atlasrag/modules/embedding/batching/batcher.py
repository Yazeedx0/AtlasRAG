import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from atlasrag.contracts.embedding import EmbeddingProvider
from atlasrag.contracts.error.embedding_errors import EmbeddingProviderTransientError
from atlasrag.contracts.types.embedding import (
    ChunkVector,
    EmbeddableChunk,
    EmbeddingBatchRequest,
    EmbeddingModelState,
    EmbeddingUsage,
)
from atlasrag.modules.embedding.config import EmbeddingRunConfig

from ._retry import backoff_seconds, default_jitter
from .planner import EmbeddingBatch, plan_batches
from .validation import build_inputs, ordered_vectors


@dataclass(frozen=True, slots=True)
class EmbeddingBatchOutcome:
    vectors: tuple[ChunkVector, ...]
    batch_count: int
    request_count: int
    usage: EmbeddingUsage


class EmbeddingBatcher:
    def __init__(
        self,
        *,
        provider: EmbeddingProvider,
        model: EmbeddingModelState,
        config: EmbeddingRunConfig,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        jitter: Callable[[], float] = default_jitter,
    ) -> None:
        self._provider = provider
        self._model = model
        self._config = config
        self._sleep = sleep or asyncio.sleep
        self._jitter = jitter

    async def embed(self, *, chunks: tuple[EmbeddableChunk, ...]) -> EmbeddingBatchOutcome:
        batches = plan_batches(chunks=chunks, config=self._config)
        semaphore = asyncio.Semaphore(self._config.concurrency)

        async def run(batch: EmbeddingBatch) -> tuple[tuple[ChunkVector, ...], int, EmbeddingUsage]:
            async with semaphore:
                return await self._embed_batch(batch=batch)

        results = await asyncio.gather(*(run(batch) for batch in batches))

        vectors: list[ChunkVector] = []
        usage = EmbeddingUsage()
        request_count = 0
        for batch_vectors, batch_requests, batch_usage in results:
            vectors.extend(batch_vectors)
            request_count += batch_requests
            usage = usage.merged_with(batch_usage)

        return EmbeddingBatchOutcome(
            vectors=tuple(vectors),
            batch_count=len(batches),
            request_count=request_count,
            usage=usage,
        )

    async def _embed_batch(
        self,
        *,
        batch: EmbeddingBatch,
    ) -> tuple[tuple[ChunkVector, ...], int, EmbeddingUsage]:
        inputs = build_inputs(chunks=batch.chunks, model=self._model, config=self._config)
        request = EmbeddingBatchRequest(model_name=self._model.model_name, inputs=inputs)

        attempt_number = 0
        while True:
            attempt_number += 1
            try:
                result = await self._provider.embed(request=request)
            except EmbeddingProviderTransientError as error:
                if attempt_number >= self._config.max_provider_attempts:
                    raise
                await self._sleep(
                    backoff_seconds(
                        attempt_number=attempt_number,
                        config=self._config,
                        retry_after_seconds=error.retry_after_seconds,
                        jitter=self._jitter(),
                    )
                )
                continue

            values = ordered_vectors(
                result=result,
                inputs=inputs,
                dimension=self._model.dimension,
            )
            vectors = tuple(
                ChunkVector(chunk_id=chunk.chunk_id, values=chunk_values)
                for chunk, chunk_values in zip(batch.chunks, values, strict=True)
            )
            return vectors, attempt_number, result.usage


__all__ = ["EmbeddingBatchOutcome", "EmbeddingBatcher"]
