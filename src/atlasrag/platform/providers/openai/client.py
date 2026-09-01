from openai import AsyncOpenAI

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.error.ai_errors import MissingProviderCredentials
from atlasrag.contracts.types.ai_types import AiProvider


def get_openai_client(settings: Settings) -> AsyncOpenAI:
    if settings.OPENAI_API_KEY is None:
        raise MissingProviderCredentials(provider=AiProvider.OPENAI)
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.OPENAI_TIMEOUT_SECONDS,
        max_retries=settings.OPENAI_MAX_RETRIES,
    )


__all__ = ["get_openai_client"]
