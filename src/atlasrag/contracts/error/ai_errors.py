from atlasrag.contracts.types.ai_types import AiCapability, AiProvider


class AiError(Exception):
    """Base error for AI capability operations."""


class UnsupportedProviderCapability(AiError):
    def __init__(self, *, provider: AiProvider, capability: AiCapability) -> None:
        self.provider = provider
        self.capability = capability
        super().__init__(f"provider {provider.value!r} does not implement {capability.value}")


class MissingProviderCredentials(AiError):
    def __init__(self, *, provider: AiProvider) -> None:
        self.provider = provider
        super().__init__(f"provider {provider.value!r} is not configured with an API key")


__all__ = ["AiError", "MissingProviderCredentials", "UnsupportedProviderCapability"]
