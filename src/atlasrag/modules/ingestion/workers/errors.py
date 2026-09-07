class IngestionWorkerError(Exception):
    """Base error for ingestion-worker orchestration failures."""


class TransientIngestionError(IngestionWorkerError):
    """The job may succeed if executed again."""


class PermanentIngestionError(IngestionWorkerError):
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


class IngestionLeaseLost(IngestionWorkerError):
    """This worker no longer owns the ingestion attempt."""


__all__ = [
    "IngestionLeaseLost",
    "IngestionWorkerError",
    "PermanentIngestionError",
    "TransientIngestionError",
]
