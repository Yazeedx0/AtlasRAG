import pytest

from atlasrag.contracts.error.embedding_errors import (
    EmbeddingInputInvalid,
    EmbeddingInputTooLarge,
    EmbeddingModelNotRegistered,
    EmbeddingVectorInvalid,
)
from atlasrag.contracts.types.ai_types import EmbeddingInputType
from atlasrag.contracts.types.embedding import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingVector,
    VectorDistanceMetric,
)
from atlasrag.modules.embedding.services import QueryEmbeddingService

from .conftest import DIMENSION, default_model_identity

pytestmark = pytest.mark.integration

MAX_CHARS_PER_TOKEN = 4


class FakeQueryProvider:
    def __init__(self, *, dimension: int = DIMENSION) -> None:
        self.dimension = dimension
        self.requests: list[EmbeddingBatchRequest] = []

    async def embed(self, *, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        self.requests.append(request)
        return EmbeddingBatchResult(
            vectors=tuple(
                EmbeddingVector(index=item.index, values=tuple([0.5] * self.dimension))
                for item in request.inputs
            ),
            model=request.model_name,
        )


def make_service(embedding_world, provider: FakeQueryProvider, **identity_overrides: object):
    return QueryEmbeddingService(
        registry=embedding_world.registry,
        provider=provider,
        identity=default_model_identity(**identity_overrides),
        max_chars_per_token=MAX_CHARS_PER_TOKEN,
    )


@pytest.mark.asyncio
async def test_query_is_embedded_with_the_registered_model(embedding_world) -> None:
    model_id = await embedding_world.registry.register(identity=default_model_identity())
    provider = FakeQueryProvider()

    vector = await make_service(embedding_world, provider).embed_query(query="  annual leave  ")

    assert vector.embedding_model_id == model_id
    assert vector.dimension == DIMENSION
    assert vector.distance_metric is VectorDistanceMetric.COSINE
    assert vector.values == tuple([0.5] * DIMENSION)
    (request,) = provider.requests
    assert request.input_type is EmbeddingInputType.QUERY
    assert request.model_name == "text-embedding-3-small"
    assert [item.text for item in request.inputs] == ["annual leave"]


@pytest.mark.asyncio
async def test_unregistered_model_is_rejected_without_calling_the_provider(
    embedding_world,
) -> None:
    provider = FakeQueryProvider()

    with pytest.raises(EmbeddingModelNotRegistered):
        await make_service(embedding_world, provider).embed_query(query="annual leave")

    assert provider.requests == []


@pytest.mark.asyncio
async def test_blank_query_is_rejected(embedding_world) -> None:
    await embedding_world.registry.register(identity=default_model_identity())
    provider = FakeQueryProvider()

    with pytest.raises(EmbeddingInputInvalid):
        await make_service(embedding_world, provider).embed_query(query="   ")

    assert provider.requests == []


@pytest.mark.asyncio
async def test_provider_vector_with_wrong_dimension_is_rejected(embedding_world) -> None:
    await embedding_world.registry.register(identity=default_model_identity())

    with pytest.raises(EmbeddingVectorInvalid):
        await make_service(
            embedding_world, FakeQueryProvider(dimension=DIMENSION + 1)
        ).embed_query(query="annual leave")


@pytest.mark.asyncio
async def test_query_over_the_model_input_limit_is_rejected(embedding_world) -> None:
    await embedding_world.registry.register(identity=default_model_identity(max_input_tokens=2))
    provider = FakeQueryProvider()

    with pytest.raises(EmbeddingInputTooLarge):
        await make_service(embedding_world, provider, max_input_tokens=2).embed_query(
            query="a query longer than eight characters"
        )

    assert provider.requests == []
