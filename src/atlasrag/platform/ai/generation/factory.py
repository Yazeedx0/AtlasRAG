from collections.abc import Callable

from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.ai import TextGenerator
from atlasrag.contracts.error.ai_errors import UnsupportedProviderCapability
from atlasrag.contracts.types.ai_types import AiCapability, AiProvider
from atlasrag.platform.providers import (
    get_anthropic_client,
    get_gemini_client,
    get_openai_client,
)

from .providers.anthropic import AnthropicTextGenerator
from .providers.gemini import GeminiTextGenerator
from .providers.openai import OpenAITextGenerator


def _openai(settings: Settings) -> TextGenerator:
    return OpenAITextGenerator(
        client=get_openai_client(settings),
        model=settings.GENERATION_MODEL,
    )


def _anthropic(settings: Settings) -> TextGenerator:
    return AnthropicTextGenerator(
        client=get_anthropic_client(settings),
        model=settings.GENERATION_MODEL,
    )


def _gemini(settings: Settings) -> TextGenerator:
    return GeminiTextGenerator(
        client=get_gemini_client(settings),
        model=settings.GENERATION_MODEL,
    )


_GENERATORS: dict[AiProvider, Callable[[Settings], TextGenerator]] = {
    AiProvider.OPENAI: _openai,
    AiProvider.ANTHROPIC: _anthropic,
    AiProvider.GEMINI: _gemini,
}


def create_text_generator(settings: Settings) -> TextGenerator:
    provider = settings.GENERATION_PROVIDER
    build = _GENERATORS.get(provider)
    if build is None:
        raise UnsupportedProviderCapability(
            provider=provider,
            capability=AiCapability.GENERATION,
        )
    return build(settings)


__all__ = ["create_text_generator"]
