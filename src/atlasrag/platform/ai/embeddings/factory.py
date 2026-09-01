from collections.abc import Callable

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.ai import Embedder
from atlasrag.contracts.error.ai_errors import UnsupportedProviderCapability
from atlasrag.contracts.types.ai_types import AiCapability, AiProvider
from atlasrag.platform.providers import (
    get_cohere_client,
    get_gemini_client,
    get_openai_client,
)

from .providers.cohere import CohereEmbedder
from .providers.gemini import GeminiEmbedder
from .providers.openai import OpenAIEmbedder


def _openai(settings: Settings) -> Embedder:
    return OpenAIEmbedder(
        client=get_openai_client(settings),
        model=settings.EMBEDDING_MODEL,
    )


def _cohere(settings: Settings) -> Embedder:
    return CohereEmbedder(
        client=get_cohere_client(settings),
        model=settings.EMBEDDING_MODEL,
    )


def _gemini(settings: Settings) -> Embedder:
    return GeminiEmbedder(
        client=get_gemini_client(settings),
        model=settings.EMBEDDING_MODEL,
    )


_EMBEDDERS: dict[AiProvider, Callable[[Settings], Embedder]] = {
    AiProvider.OPENAI: _openai,
    AiProvider.COHERE: _cohere,
    AiProvider.GEMINI: _gemini,
}


def create_embedder(settings: Settings) -> Embedder:
    provider = settings.EMBEDDING_PROVIDER
    build = _EMBEDDERS.get(provider)
    if build is None:
        raise UnsupportedProviderCapability(
            provider=provider,
            capability=AiCapability.EMBEDDING,
        )
    return build(settings)


__all__ = ["create_embedder"]
