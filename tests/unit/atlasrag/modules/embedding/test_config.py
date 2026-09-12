import pytest

from atlasrag.modules.embedding.config import (
    DEFAULT_EMBEDDING_RUN_CONFIG,
    EmbeddingRunConfig,
)

pytestmark = pytest.mark.unit


def test_default_configuration_round_trips_through_a_run_configuration() -> None:
    configuration = {"embedding": DEFAULT_EMBEDDING_RUN_CONFIG.as_mapping()}

    assert EmbeddingRunConfig.from_run_configuration(configuration) == (
        DEFAULT_EMBEDDING_RUN_CONFIG
    )


def test_missing_embedding_section_is_rejected() -> None:
    with pytest.raises(ValueError, match="embedding object"):
        EmbeddingRunConfig.from_run_configuration({"chunking": {}})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("batch_size", 0),
        ("max_batch_tokens", 0),
        ("concurrency", 0),
        ("max_provider_attempts", 0),
        ("max_chars_per_token", 0),
    ],
)
def test_non_positive_values_are_rejected(field: str, value: int) -> None:
    values = {**DEFAULT_EMBEDDING_RUN_CONFIG.as_mapping(), field: value}

    with pytest.raises(ValueError, match="must be positive"):
        EmbeddingRunConfig.from_run_configuration({"embedding": values})


def test_backoff_ceiling_below_the_initial_backoff_is_rejected() -> None:
    values = {
        **DEFAULT_EMBEDDING_RUN_CONFIG.as_mapping(),
        "retry_initial_backoff_seconds": 5.0,
        "retry_max_backoff_seconds": 1.0,
    }

    with pytest.raises(ValueError, match="retry_max_backoff_seconds"):
        EmbeddingRunConfig.from_run_configuration({"embedding": values})


def test_boolean_is_not_accepted_as_an_integer() -> None:
    values = {**DEFAULT_EMBEDDING_RUN_CONFIG.as_mapping(), "batch_size": True}

    with pytest.raises(ValueError, match="batch_size must be an integer"):
        EmbeddingRunConfig.from_run_configuration({"embedding": values})
