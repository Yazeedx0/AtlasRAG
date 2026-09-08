from google.genai import Client
from google.genai.types import HttpOptions, HttpRetryOptions
from openai import AsyncOpenAI

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.error.ai_errors import MissingProviderCredentials
from atlasrag.contracts.extraction import DocumentExtractor
from atlasrag.contracts.types.ai_types import AiProvider

from .providers.gemini import VlmDocumentExtractor
from .providers.openai import OpenAIOcrExtractor

_SECONDS_TO_MILLISECONDS = 1000


def create_ocr_extractor(settings: Settings) -> DocumentExtractor:
    if not settings.OPENAI_API_KEY:
        raise MissingProviderCredentials(provider=AiProvider.OPENAI)

    return OpenAIOcrExtractor(
        client=AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.EXTRACTION_TIMEOUT_SECONDS,
            max_retries=settings.EXTRACTION_MAX_RETRIES,
        ),
        model=settings.OCR_MODEL,
        max_output_tokens=settings.OCR_MAX_OUTPUT_TOKENS,
    )


def create_vlm_extractor(settings: Settings) -> DocumentExtractor:
    if not settings.GEMINI_API_KEY:
        raise MissingProviderCredentials(provider=AiProvider.GEMINI)

    return VlmDocumentExtractor(
        client=Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=HttpOptions(
                timeout=int(settings.EXTRACTION_TIMEOUT_SECONDS * _SECONDS_TO_MILLISECONDS),
                retry_options=HttpRetryOptions(attempts=settings.EXTRACTION_MAX_RETRIES),
            ),
        ),
        model=settings.VLM_MODEL,
        max_output_tokens=settings.VLM_MAX_OUTPUT_TOKENS,
    )


__all__ = ["create_ocr_extractor", "create_vlm_extractor"]
