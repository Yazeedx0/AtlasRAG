class IngestionError(Exception):
    """Base error for ingestion persistence operations."""


class ChunkSetImmutable(IngestionError):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(f"chunk set is immutable: {reason}")


__all__ = ["ChunkSetImmutable", "IngestionError"]
