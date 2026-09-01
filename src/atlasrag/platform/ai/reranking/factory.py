from collections.abc import Callable

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.ai import Reranker
from atlasrag.contracts.error.ai_errors import UnsupportedProviderCapability
from atlasrag.contracts.types.ai_types import AiCapability, AiProvider
from atlasrag.platform.providers import get_cohere_client

from .providers.cohere import CohereReranker


def _cohere(settings: Settings) -> Reranker:
    return CohereReranker(
        client=get_cohere_client(settings),
        model=settings.RERANK_MODEL,
    )


_RERANKERS: dict[AiProvider, Callable[[Settings], Reranker]] = {
    AiProvider.COHERE: _cohere,
}


def create_reranker(settings: Settings) -> Reranker:
    provider = settings.RERANK_PROVIDER
    build = _RERANKERS.get(provider)
    if build is None:
        raise UnsupportedProviderCapability(
            provider=provider,
            capability=AiCapability.RERANK,
        )
    return build(settings)


__all__ = ["create_reranker"]
