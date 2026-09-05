class ObjectStorageError(Exception):
    """Base error for object storage operations."""


class ObjectNotFound(ObjectStorageError):
    def __init__(self, *, key: str) -> None:
        self.key = key
        super().__init__(f"object {key!r} not found in storage")


class ObjectStorageUnavailable(ObjectStorageError):
    def __init__(self, *, operation: str, key: str) -> None:
        self.operation = operation
        self.key = key
        super().__init__(
            f"object storage operation {operation!r} is unavailable for key {key!r}"
        )


__all__ = ["ObjectNotFound", "ObjectStorageError", "ObjectStorageUnavailable"]
