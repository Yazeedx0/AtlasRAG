class ObjectStorageError(Exception):
    """Base error for object storage operations."""


class ObjectNotFound(ObjectStorageError):
    def __init__(self, *, key: str) -> None:
        self.key = key
        super().__init__(f"object {key!r} not found in storage")


__all__ = ["ObjectNotFound", "ObjectStorageError"]
