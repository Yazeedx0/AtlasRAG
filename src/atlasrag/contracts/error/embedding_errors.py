class EmbeddingError(Exception):
    """Base error for embedding operations."""


class EmbeddingProviderTransientError(EmbeddingError):
    def __init__(self, *, reason: str, retry_after_seconds: float | None = None) -> None:
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"embedding provider failed transiently: {reason}")


class EmbeddingProviderPermanentError(EmbeddingError):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(f"embedding provider failed permanently: {reason}")


class InvalidEmbeddingResponse(EmbeddingError):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(f"embedding provider returned an invalid response: {reason}")


class EmbeddingInputTooLarge(EmbeddingError):
    def __init__(self, *, chunk_index: int | None = None, reason: str) -> None:
        self.chunk_index = chunk_index
        self.reason = reason
        super().__init__(f"embedding input exceeds the model limit: {reason}")


class EmbeddingInputInvalid(EmbeddingError):
    def __init__(self, *, chunk_index: int | None = None, reason: str) -> None:
        self.chunk_index = chunk_index
        self.reason = reason
        super().__init__(f"embedding input is not embeddable: {reason}")


class EmbeddingVectorInvalid(EmbeddingError):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(f"embedding provider returned an invalid vector: {reason}")


class IngestionItemNotEmbeddable(EmbeddingError):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(f"ingestion item cannot be embedded: {reason}")


class EmbeddingRunAlreadyInFlight(EmbeddingError):
    def __init__(self, *, ingestion_item_id: str, embedding_model_id: str) -> None:
        self.ingestion_item_id = ingestion_item_id
        self.embedding_model_id = embedding_model_id
        super().__init__(
            "an embedding run for this ingestion item and model is already in flight"
        )


class ChunkSetChanged(EmbeddingError):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(f"chunk set changed during the embedding run: {reason}")


__all__ = [
    "ChunkSetChanged",
    "EmbeddingError",
    "EmbeddingInputInvalid",
    "EmbeddingInputTooLarge",
    "EmbeddingProviderPermanentError",
    "EmbeddingProviderTransientError",
    "EmbeddingRunAlreadyInFlight",
    "EmbeddingVectorInvalid",
    "IngestionItemNotEmbeddable",
    "InvalidEmbeddingResponse",
]
