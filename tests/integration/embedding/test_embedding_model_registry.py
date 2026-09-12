import pytest

from atlasrag.contracts.types.ai_types import AiProvider
from atlasrag.contracts.types.embedding import (
    EmbeddingModelIdentity,
    VectorDistanceMetric,
)
from atlasrag.platform.configuration_hash import canonical_configuration_hash

from .conftest import default_model_identity

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_model_identity_is_persisted(embedding_world) -> None:
    identity = default_model_identity(
        dimension=1536,
        max_input_tokens=8191,
        configuration={"normalize": True},
    )

    model_id = await embedding_world.registry.register(identity=identity)
    model = await embedding_world.registry.find_model(model_id=model_id)

    assert model is not None
    assert model.provider is AiProvider.OPENAI
    assert model.model_name == "text-embedding-3-small"
    assert model.model_revision == "v1"
    assert model.dimension == 1536
    assert model.distance_metric is VectorDistanceMetric.COSINE
    assert model.max_input_tokens == 8191
    assert model.configuration == {"normalize": True}


@pytest.mark.asyncio
async def test_configuration_hash_is_canonical_and_stable(embedding_world) -> None:
    first = await embedding_world.registry.register(
        identity=default_model_identity(configuration={"a": 1, "b": 2})
    )
    second = await embedding_world.registry.register(
        identity=default_model_identity(configuration={"b": 2, "a": 1})
    )
    model = await embedding_world.registry.find_model(model_id=first)

    assert first == second
    assert model is not None
    assert model.configuration_hash == canonical_configuration_hash({"a": 1, "b": 2})


@pytest.mark.asyncio
async def test_registering_the_same_identity_twice_reuses_the_record(embedding_world) -> None:
    identity = default_model_identity()

    first = await embedding_world.registry.register(identity=identity)
    second = await embedding_world.registry.register(identity=identity)

    assert first == second


@pytest.mark.asyncio
async def test_a_different_revision_is_a_separate_model(embedding_world) -> None:
    first = await embedding_world.registry.register(
        identity=default_model_identity(model_revision="v1")
    )
    second = await embedding_world.registry.register(
        identity=default_model_identity(model_revision="v2")
    )

    assert first != second


@pytest.mark.asyncio
async def test_a_materially_different_configuration_is_a_separate_model(
    embedding_world,
) -> None:
    first = await embedding_world.registry.register(
        identity=default_model_identity(configuration={"dimensions": 512})
    )
    second = await embedding_world.registry.register(
        identity=default_model_identity(configuration={"dimensions": 1536})
    )
    first_model = await embedding_world.registry.find_model(model_id=first)
    second_model = await embedding_world.registry.find_model(model_id=second)

    assert first != second
    assert first_model is not None
    assert second_model is not None
    assert first_model.configuration != second_model.configuration


@pytest.mark.asyncio
async def test_a_different_provider_is_a_separate_model(embedding_world) -> None:
    openai_model = await embedding_world.registry.register(identity=default_model_identity())
    cohere_model = await embedding_world.registry.register(
        identity=EmbeddingModelIdentity(
            provider=AiProvider.COHERE,
            model_name="text-embedding-3-small",
            model_revision="v1",
            dimension=1024,
            distance_metric=VectorDistanceMetric.COSINE,
        )
    )

    assert openai_model != cohere_model


@pytest.mark.parametrize("dimension", [0, -1])
def test_non_positive_dimension_is_rejected(dimension: int) -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        default_model_identity(dimension=dimension)


def test_non_positive_max_input_tokens_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_input_tokens must be positive"):
        default_model_identity(max_input_tokens=0)


def test_blank_model_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="model_name"):
        default_model_identity(model_name="   ")
