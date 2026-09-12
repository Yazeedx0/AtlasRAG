from collections.abc import Callable

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.embedding import EmbeddingProvider
from atlasrag.contracts.error.ai_errors import UnsupportedProviderCapability
from atlasrag.contracts.types.ai_types import AiCapability, AiProvider
from atlasrag.platform.providers import get_openai_client

from .providers.openai_provider import OpenAIEmbeddingProvider


def _openai(settings: Settings) -> EmbeddingProvider:
    return OpenAIEmbeddingProvider(client=get_openai_client(settings))


_PROVIDERS: dict[AiProvider, Callable[[Settings], EmbeddingProvider]] = {
    AiProvider.OPENAI: _openai,
}


def create_embedding_provider(
    settings: Settings,
    *,
    provider: AiProvider | None = None,
) -> EmbeddingProvider:
    selected = provider or settings.EMBEDDING_PROVIDER
    build = _PROVIDERS.get(selected)
    if build is None:
        raise UnsupportedProviderCapability(
            provider=selected,
            capability=AiCapability.EMBEDDING,
        )
    return build(settings)


__all__ = ["create_embedding_provider"]
