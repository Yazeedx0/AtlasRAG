"""Tests use ``_env_file=None`` to bypass the repo's local ``.env`` file, so
results don't depend on what a given developer's machine has set.
"""

import pytest

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.error.ai_errors import (
    MissingProviderCredentials,
    UnsupportedProviderCapability,
)
from atlasrag.contracts.types.ai_types import AiCapability, AiProvider
from atlasrag.platform.ai import create_embedder, create_reranker, create_text_generator
from atlasrag.platform.ai.embeddings.providers import (
    CohereEmbedder,
    GeminiEmbedder,
    OpenAIEmbedder,
)
from atlasrag.platform.ai.generation.providers import (
    AnthropicTextGenerator,
    GeminiTextGenerator,
    OpenAITextGenerator,
)
from atlasrag.platform.ai.reranking.providers import CohereReranker

pytestmark = pytest.mark.unit

_CREDENTIALS = {
    "ATLAS_DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/db",
    "ATLAS_OPENAI_API_KEY": "openai-key",
    "ATLAS_ANTHROPIC_API_KEY": "anthropic-key",
    "ATLAS_COHERE_API_KEY": "cohere-key",
    "ATLAS_GEMINI_API_KEY": "gemini-key",
}


@pytest.fixture
def make_settings(monkeypatch):
    def _make(**env_vars: str) -> Settings:
        for key, value in {**_CREDENTIALS, **env_vars}.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=None)

    return _make


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("openai", OpenAITextGenerator),
        ("anthropic", AnthropicTextGenerator),
        ("gemini", GeminiTextGenerator),
    ],
)
def test_generation_provider_resolves_to_its_adapter(make_settings, provider, expected):
    settings = make_settings(ATLAS_GENERATION_PROVIDER=provider)

    assert isinstance(create_text_generator(settings), expected)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("openai", OpenAIEmbedder),
        ("cohere", CohereEmbedder),
        ("gemini", GeminiEmbedder),
    ],
)
def test_embedding_provider_resolves_to_its_adapter(make_settings, provider, expected):
    settings = make_settings(ATLAS_EMBEDDING_PROVIDER=provider)

    assert isinstance(create_embedder(settings), expected)


def test_rerank_provider_resolves_to_its_adapter(make_settings):
    settings = make_settings(ATLAS_RERANK_PROVIDER="cohere")

    assert isinstance(create_reranker(settings), CohereReranker)


def test_capabilities_resolve_to_independent_providers(make_settings):
    settings = make_settings(
        ATLAS_GENERATION_PROVIDER="anthropic",
        ATLAS_EMBEDDING_PROVIDER="cohere",
        ATLAS_RERANK_PROVIDER="cohere",
    )

    assert isinstance(create_text_generator(settings), AnthropicTextGenerator)
    assert isinstance(create_embedder(settings), CohereEmbedder)
    assert isinstance(create_reranker(settings), CohereReranker)


def test_changing_only_the_model_keeps_the_provider(make_settings):
    settings = make_settings(
        ATLAS_GENERATION_PROVIDER="openai",
        ATLAS_GENERATION_MODEL="gpt-4o",
    )

    generator = create_text_generator(settings)

    assert isinstance(generator, OpenAITextGenerator)
    assert generator._model == "gpt-4o"


def test_embedding_model_comes_from_configuration(make_settings):
    settings = make_settings(
        ATLAS_EMBEDDING_PROVIDER="cohere",
        ATLAS_EMBEDDING_MODEL="embed-multilingual-v3.0",
    )

    assert create_embedder(settings)._model == "embed-multilingual-v3.0"


@pytest.mark.parametrize(
    ("env_var", "provider", "factory", "capability"),
    [
        (
            "ATLAS_GENERATION_PROVIDER",
            "cohere",
            create_text_generator,
            AiCapability.GENERATION,
        ),
        (
            "ATLAS_EMBEDDING_PROVIDER",
            "anthropic",
            create_embedder,
            AiCapability.EMBEDDING,
        ),
        (
            "ATLAS_RERANK_PROVIDER",
            "openai",
            create_reranker,
            AiCapability.RERANK,
        ),
    ],
)
def test_unsupported_provider_capability_fails_clearly(
    make_settings,
    env_var,
    provider,
    factory,
    capability,
):
    settings = make_settings(**{env_var: provider})

    with pytest.raises(UnsupportedProviderCapability) as error:
        factory(settings)

    assert error.value.provider is AiProvider(provider)
    assert error.value.capability is capability


def test_unknown_provider_is_rejected_by_settings_validation(make_settings):
    with pytest.raises(ValueError):
        make_settings(ATLAS_GENERATION_PROVIDER="not-a-provider")


def test_missing_credentials_fail_clearly(monkeypatch):
    monkeypatch.setenv("ATLAS_DATABASE_URL", _CREDENTIALS["ATLAS_DATABASE_URL"])
    monkeypatch.setenv("ATLAS_GENERATION_PROVIDER", "openai")
    settings = Settings(_env_file=None)

    with pytest.raises(MissingProviderCredentials) as error:
        create_text_generator(settings)

    assert error.value.provider is AiProvider.OPENAI
