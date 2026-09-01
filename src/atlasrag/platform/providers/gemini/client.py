from google.genai import Client
from google.genai.types import HttpOptions, HttpRetryOptions

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.error.ai_errors import MissingProviderCredentials
from atlasrag.contracts.types.ai_types import AiProvider

_SECONDS_TO_MILLISECONDS = 1000


def get_gemini_client(settings: Settings) -> Client:
    if settings.GEMINI_API_KEY is None:
        raise MissingProviderCredentials(provider=AiProvider.GEMINI)
    return Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=HttpOptions(
            timeout=int(settings.GEMINI_TIMEOUT_SECONDS * _SECONDS_TO_MILLISECONDS),
            retry_options=HttpRetryOptions(attempts=settings.GEMINI_MAX_RETRIES),
        ),
    )


__all__ = ["get_gemini_client"]
