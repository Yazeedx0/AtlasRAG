from anthropic import AsyncAnthropic

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.error.ai_errors import MissingProviderCredentials
from atlasrag.contracts.types.ai_types import AiProvider


def get_anthropic_client(settings: Settings) -> AsyncAnthropic:
    if settings.ANTHROPIC_API_KEY is None:
        raise MissingProviderCredentials(provider=AiProvider.ANTHROPIC)
    return AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=settings.ANTHROPIC_TIMEOUT_SECONDS,
        max_retries=settings.ANTHROPIC_MAX_RETRIES,
    )


__all__ = ["get_anthropic_client"]
