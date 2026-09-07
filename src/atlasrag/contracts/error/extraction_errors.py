from atlasrag.contracts.types.extraction import ExtractionMethod


class ExtractionError(Exception):
    """Base error for document extraction operations."""


class ExtractionProviderTransientError(ExtractionError):
    def __init__(self, *, method: ExtractionMethod, reason: str) -> None:
        self.method = method
        self.reason = reason
        super().__init__(f"extraction via {method.value!r} failed transiently: {reason}")


class ExtractionProviderPermanentError(ExtractionError):
    def __init__(self, *, method: ExtractionMethod, reason: str) -> None:
        self.method = method
        self.reason = reason
        super().__init__(f"extraction via {method.value!r} failed permanently: {reason}")


class ExtractionFailed(ExtractionError):
    def __init__(
        self,
        *,
        primary_reason: str,
        fallback_reason: str,
        retryable: bool,
    ) -> None:
        self.primary_reason = primary_reason
        self.fallback_reason = fallback_reason
        self.retryable = retryable
        super().__init__(
            f"extraction failed on primary ({primary_reason}) and fallback ({fallback_reason})"
        )


__all__ = [
    "ExtractionError",
    "ExtractionFailed",
    "ExtractionProviderPermanentError",
    "ExtractionProviderTransientError",
]
