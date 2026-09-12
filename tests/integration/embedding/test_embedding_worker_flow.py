from datetime import timedelta

import pytest

from atlasrag.contracts.error.embedding_errors import EmbeddingProviderTransientError
from atlasrag.contracts.types.embedding import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingStatus,
    EmbeddingUsage,
    EmbeddingVector,
)
from atlasrag.modules.embedding.workers import (
    DefaultEmbeddingProcessor,
    EmbeddingJobHandler,
    EmbeddingLeaseHeartbeat,
)
from atlasrag.modules.embedding.workers.job_handler import TRANSIENT_EMBEDDING_ERROR

from .conftest import (
    DIMENSION,
    LEASE_DURATION,
    default_model_identity,
    embedding_run_configuration,
    stored_embeddings,
    vectors_for,
)

pytestmark = pytest.mark.integration

HEARTBEAT_INTERVAL = timedelta(seconds=30)


class DeterministicProvider:
    def __init__(self, *, dimension: int = DIMENSION) -> None:
        self._dimension = dimension
        self.requests: list[EmbeddingBatchRequest] = []

    async def embed(self, *, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        self.requests.append(request)
        return EmbeddingBatchResult(
            vectors=tuple(
                EmbeddingVector(
                    index=item.index,
                    values=tuple(float(len(item.text) % 7) for _ in range(self._dimension)),
                )
                for item in reversed(request.inputs)
            ),
            model=request.model_name,
            usage=EmbeddingUsage(
                input_tokens=len(request.inputs),
                total_tokens=len(request.inputs),
            ),
        )


class UnavailableProvider:
    async def embed(self, *, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        raise EmbeddingProviderTransientError(reason="http_503")


class WrongDimensionProvider:
    async def embed(self, *, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        return EmbeddingBatchResult(
            vectors=tuple(
                EmbeddingVector(index=item.index, values=(0.1, 0.2))
                for item in request.inputs
            ),
            model=request.model_name,
        )


def make_handler(world, provider) -> EmbeddingJobHandler:
    return EmbeddingJobHandler(
        lifecycle=world.embedding,
        processor=DefaultEmbeddingProcessor(
            lifecycle=world.embedding,
            provider_factory=lambda model: provider,
        ),
        heartbeat=EmbeddingLeaseHeartbeat(world.embedding, interval=HEARTBEAT_INTERVAL),
    )


async def prepare_run(world, seeded, **overrides):
    model_id = await world.registry.register(identity=default_model_identity())
    run_id = await world.embedding.create_run(
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        configuration=embedding_run_configuration(**overrides),
    )
    return model_id, run_id


@pytest.mark.asyncio
async def test_worker_embeds_every_chunk_and_completes_the_run(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=75)
    model_id, run_id = await prepare_run(embedding_world, seeded, batch_size=16)
    provider = DeterministicProvider()

    await make_handler(embedding_world, provider).handle(embedding_run_id=run_id)

    run = await embedding_world.embedding.find_run(run_id=run_id)
    rows = await stored_embeddings(embedding_world, model_id)

    assert run is not None
    assert run.status is EmbeddingStatus.COMPLETED
    assert run.attempt_count == 1
    assert len(rows) == 75
    assert {row.chunk_id for row in rows} == set(seeded.chunk_ids)
    assert all(len(row.embedding) == DIMENSION for row in rows)
    assert [len(request.inputs) for request in provider.requests] == [16, 16, 16, 16, 11]
    assert run.execution_metadata["embedding"] == {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "model_revision": "v1",
        "dimension": DIMENSION,
        "distance_metric": "cosine",
        "batch_count": 5,
        "request_count": 5,
        "embedded_chunk_count": 75,
        "input_tokens": 75,
        "total_tokens": 75,
        "batch_size": 16,
        "max_batch_tokens": 100000,
        "concurrency": 4,
    }


@pytest.mark.asyncio
async def test_completing_an_embedding_run_does_not_activate_the_ingestion_item(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=3)
    _, run_id = await prepare_run(embedding_world, seeded)

    await make_handler(embedding_world, DeterministicProvider()).handle(
        embedding_run_id=run_id
    )

    item = await embedding_world.ingestion.find_item(item_id=seeded.ingestion_item_id)
    assert item is not None
    assert item.activated_at is None
    assert item.deactivated_at is None


@pytest.mark.asyncio
async def test_duplicate_delivery_embeds_the_run_only_once(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=4)
    model_id, run_id = await prepare_run(embedding_world, seeded)
    provider = DeterministicProvider()
    handler = make_handler(embedding_world, provider)

    await handler.handle(embedding_run_id=run_id)
    await handler.handle(embedding_run_id=run_id)

    run = await embedding_world.embedding.find_run(run_id=run_id)
    rows = await stored_embeddings(embedding_world, model_id)

    assert run is not None
    assert run.attempt_count == 1
    assert len(provider.requests) == 1
    assert len(rows) == 4


@pytest.mark.asyncio
async def test_transient_provider_failure_releases_the_run_for_a_durable_retry(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=2)
    model_id, run_id = await prepare_run(embedding_world, seeded, max_provider_attempts=1)

    await make_handler(embedding_world, UnavailableProvider()).handle(embedding_run_id=run_id)

    run = await embedding_world.embedding.find_run(run_id=run_id)
    assert run is not None
    assert run.status is EmbeddingStatus.PENDING
    assert run.error_code == TRANSIENT_EMBEDDING_ERROR
    assert await stored_embeddings(embedding_world, model_id) == []


@pytest.mark.asyncio
async def test_invalid_vector_dimension_fails_the_run_without_persisting(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=2)
    model_id, run_id = await prepare_run(embedding_world, seeded)

    await make_handler(embedding_world, WrongDimensionProvider()).handle(
        embedding_run_id=run_id
    )

    run = await embedding_world.embedding.find_run(run_id=run_id)
    assert run is not None
    assert run.status is EmbeddingStatus.FAILED
    assert run.error_code == "embedding_vector_invalid"
    assert await stored_embeddings(embedding_world, model_id) == []


@pytest.mark.asyncio
async def test_crashed_attempt_is_reclaimed_and_cannot_finalize_afterwards(
    embedding_world, seed_completed_item
) -> None:
    seeded = await seed_completed_item(chunk_count=9)
    model_id, run_id = await prepare_run(embedding_world, seeded)

    crashed = await embedding_world.embedding.claim(run_id=run_id)
    assert crashed is not None

    embedding_world.clock.advance(LEASE_DURATION + timedelta(seconds=1))
    await make_handler(embedding_world, DeterministicProvider()).handle(
        embedding_run_id=run_id
    )

    late_finalization = await embedding_world.embedding.persist_vectors_and_mark_completed(
        run_id=run_id,
        attempt_number=crashed.attempt_number,
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        dimension=DIMENSION,
        expected_chunk_ids=seeded.chunk_ids,
        vectors=vectors_for(seeded.chunk_ids, value=99.0),
        execution_metadata={},
    )

    run = await embedding_world.embedding.find_run(run_id=run_id)
    rows = await stored_embeddings(embedding_world, model_id)

    assert late_finalization is False
    assert run is not None
    assert run.status is EmbeddingStatus.COMPLETED
    assert run.attempt_count == 2
    assert len(rows) == 9
    assert {row.chunk_id for row in rows} == set(seeded.chunk_ids)
    assert all(row.embedding[0] != 99.0 for row in rows)
