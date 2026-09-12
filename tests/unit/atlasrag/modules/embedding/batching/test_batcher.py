import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from atlasrag.contracts.error.embedding_errors import EmbeddingProviderTransientError
from atlasrag.contracts.types.ai_types import AiProvider
from atlasrag.contracts.types.embedding import (
    EmbeddableChunk,
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingModelState,
    EmbeddingUsage,
    EmbeddingVector,
    VectorDistanceMetric,
)
from atlasrag.modules.embedding.batching import EmbeddingBatcher
from atlasrag.modules.embedding.config import DEFAULT_EMBEDDING_RUN_CONFIG

pytestmark = pytest.mark.unit

DIMENSION = 3


def make_model() -> EmbeddingModelState:
    return EmbeddingModelState(
        id=uuid.uuid4(),
        provider=AiProvider.OPENAI,
        model_name="text-embedding-3-small",
        model_revision="v1",
        dimension=DIMENSION,
        distance_metric=VectorDistanceMetric.COSINE,
        max_input_tokens=None,
        configuration={},
        configuration_hash="a" * 64,
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


def make_chunks(count: int) -> tuple[EmbeddableChunk, ...]:
    return tuple(
        EmbeddableChunk(
            chunk_id=uuid.uuid4(),
            chunk_index=index,
            content=f"chunk-{index}",
            token_count=1,
        )
        for index in range(count)
    )


class ReversingProvider:
    """Returns vectors in reverse order, each carrying its input index."""

    def __init__(self) -> None:
        self.requests: list[EmbeddingBatchRequest] = []

    async def embed(self, *, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        self.requests.append(request)
        vectors = tuple(
            EmbeddingVector(
                index=item.index,
                values=(float(item.index), float(item.index), float(item.index)),
            )
            for item in reversed(request.inputs)
        )
        return EmbeddingBatchResult(
            vectors=vectors,
            model=request.model_name,
            usage=EmbeddingUsage(input_tokens=len(request.inputs), total_tokens=len(request.inputs)),
        )


class FlakyProvider:
    def __init__(self, *, failures: int) -> None:
        self._failures = failures
        self.calls = 0

    async def embed(self, *, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        self.calls += 1
        if self.calls <= self._failures:
            raise EmbeddingProviderTransientError(reason="http_429", retry_after_seconds=7.0)
        return EmbeddingBatchResult(
            vectors=tuple(
                EmbeddingVector(index=item.index, values=(0.1, 0.2, 0.3))
                for item in request.inputs
            ),
            model=request.model_name,
        )


def make_batcher(provider: object, *, batch_size: int = 2, max_provider_attempts: int = 4):
    config = replace(
        DEFAULT_EMBEDDING_RUN_CONFIG,
        batch_size=batch_size,
        concurrency=1,
        max_provider_attempts=max_provider_attempts,
    )
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    return (
        EmbeddingBatcher(
            provider=provider,
            model=make_model(),
            config=config,
            sleep=sleep,
            jitter=lambda: 1.0,
        ),
        slept,
    )


@pytest.mark.asyncio
async def test_vectors_are_mapped_back_to_their_own_chunks() -> None:
    provider = ReversingProvider()
    batcher, _ = make_batcher(provider, batch_size=10)
    chunks = make_chunks(4)

    outcome = await batcher.embed(chunks=chunks)

    assert [vector.chunk_id for vector in outcome.vectors] == [c.chunk_id for c in chunks]
    assert [vector.values[0] for vector in outcome.vectors] == [0.0, 1.0, 2.0, 3.0]


@pytest.mark.asyncio
async def test_chunks_are_split_into_provider_batches() -> None:
    provider = ReversingProvider()
    batcher, _ = make_batcher(provider, batch_size=2)

    outcome = await batcher.embed(chunks=make_chunks(5))

    assert outcome.batch_count == 3
    assert [len(request.inputs) for request in provider.requests] == [2, 2, 1]
    assert len(outcome.vectors) == 5


@pytest.mark.asyncio
async def test_usage_is_aggregated_across_batches() -> None:
    provider = ReversingProvider()
    batcher, _ = make_batcher(provider, batch_size=2)

    outcome = await batcher.embed(chunks=make_chunks(5))

    assert outcome.usage == EmbeddingUsage(input_tokens=5, total_tokens=5)
    assert outcome.request_count == 3


@pytest.mark.asyncio
async def test_transient_failure_is_retried_and_honours_retry_after() -> None:
    provider = FlakyProvider(failures=2)
    batcher, slept = make_batcher(provider, batch_size=10)

    outcome = await batcher.embed(chunks=make_chunks(2))

    assert provider.calls == 3
    assert outcome.request_count == 3
    assert slept == [7.0, 7.0]
    assert len(outcome.vectors) == 2


@pytest.mark.asyncio
async def test_transient_failure_beyond_max_attempts_is_raised() -> None:
    provider = FlakyProvider(failures=10)
    batcher, _ = make_batcher(provider, batch_size=10, max_provider_attempts=3)

    with pytest.raises(EmbeddingProviderTransientError):
        await batcher.embed(chunks=make_chunks(2))

    assert provider.calls == 3
