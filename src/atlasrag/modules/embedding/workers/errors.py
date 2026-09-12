class EmbeddingWorkerError(Exception):
    """Base error for embedding-worker orchestration failures."""


class TransientEmbeddingError(EmbeddingWorkerError):
    """The job may succeed if executed again."""


class PermanentEmbeddingError(EmbeddingWorkerError):
    """Retrying the same input is not expected to help."""

    def __init__(
        self,
        *,
        error_code: str,
        message: str | None = None,
    ) -> None:
        super().__init__(message or error_code)
        self.error_code = error_code
        self.message = message


class EmbeddingLeaseLost(EmbeddingWorkerError):
    """This worker no longer owns the embedding attempt."""


__all__ = [
    "EmbeddingLeaseLost",
    "EmbeddingWorkerError",
    "PermanentEmbeddingError",
    "TransientEmbeddingError",
]
