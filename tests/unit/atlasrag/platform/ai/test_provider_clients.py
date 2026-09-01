"""Tests use ``_env_file=None`` to bypass the repo's local ``.env`` file, so
results don't depend on what a given developer's machine has set.
"""

import pytest
from anthropic import AsyncAnthropic
from cohere import AsyncClientV2
from google.genai import Client as GeminiClient
from openai import AsyncOpenAI

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.ai import Embedder, Reranker, TextGenerator
from atlasrag.platform.ai import create_embedder, create_reranker, create_text_generator
from atlasrag.platform.providers import (
    get_anthropic_client,
    get_cohere_client,
    get_gemini_client,
    get_openai_client,
)

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


def test_openai_client_receives_provider_configuration(make_settings):
    settings = make_settings(
        ATLAS_OPENAI_TIMEOUT_SECONDS="12.5",
        ATLAS_OPENAI_MAX_RETRIES="7",
    )

    client = get_openai_client(settings)

    assert isinstance(client, AsyncOpenAI)
    assert client.api_key == "openai-key"
    assert client.timeout == 12.5
    assert client.max_retries == 7


def test_anthropic_client_receives_provider_configuration(make_settings):
    settings = make_settings(
        ATLAS_ANTHROPIC_TIMEOUT_SECONDS="9.0",
        ATLAS_ANTHROPIC_MAX_RETRIES="4",
    )

    client = get_anthropic_client(settings)

    assert isinstance(client, AsyncAnthropic)
    assert client.api_key == "anthropic-key"
    assert client.timeout == 9.0
    assert client.max_retries == 4


def test_cohere_client_is_constructed(make_settings):
    settings = make_settings(ATLAS_COHERE_TIMEOUT_SECONDS="15.0")

    assert isinstance(get_cohere_client(settings), AsyncClientV2)


def test_gemini_client_translates_timeout_to_milliseconds(make_settings):
    settings = make_settings(
        ATLAS_GEMINI_TIMEOUT_SECONDS="20.0",
        ATLAS_GEMINI_MAX_RETRIES="5",
    )

    client = get_gemini_client(settings)
    http_options = client._api_client._http_options

    assert isinstance(client, GeminiClient)
    assert http_options.timeout == 20000
    assert http_options.retry_options.attempts == 5


@pytest.mark.parametrize(
    ("provider", "model_var", "model"),
    [
        ("openai", "ATLAS_GENERATION_MODEL", "gpt-4o"),
        ("anthropic", "ATLAS_GENERATION_MODEL", "claude-opus-5"),
        ("gemini", "ATLAS_GENERATION_MODEL", "gemini-2.0-flash"),
    ],
)
def test_generators_expose_the_capability_contract_not_a_vendor_client(
    make_settings,
    provider,
    model_var,
    model,
):
    settings = make_settings(ATLAS_GENERATION_PROVIDER=provider, **{model_var: model})

    generator = create_text_generator(settings)

    assert isinstance(generator, TextGenerator)
    assert not isinstance(generator, AsyncOpenAI | AsyncAnthropic | AsyncClientV2 | GeminiClient)
    assert hasattr(generator, "generate")


def test_embedder_and_reranker_expose_the_capability_contract(make_settings):
    settings = make_settings(
        ATLAS_EMBEDDING_PROVIDER="cohere",
        ATLAS_RERANK_PROVIDER="cohere",
    )

    embedder = create_embedder(settings)
    reranker = create_reranker(settings)

    assert isinstance(embedder, Embedder)
    assert isinstance(reranker, Reranker)
    assert not isinstance(embedder, AsyncClientV2)
    assert not isinstance(reranker, AsyncClientV2)
