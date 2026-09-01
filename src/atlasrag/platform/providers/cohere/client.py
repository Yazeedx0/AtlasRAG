from cohere import AsyncClientV2

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.error.ai_errors import MissingProviderCredentials
from atlasrag.contracts.types.ai_types import AiProvider


def get_cohere_client(settings: Settings) -> AsyncClientV2:
    if settings.COHERE_API_KEY is None:
        raise MissingProviderCredentials(provider=AiProvider.COHERE)
    return AsyncClientV2(
        api_key=settings.COHERE_API_KEY,
        timeout=settings.COHERE_TIMEOUT_SECONDS,
        max_retries=settings.COHERE_MAX_RETRIES,
    )


__all__ = ["get_cohere_client"]
