from fastapi import Request

from atlasrag.contracts.object_storage import ObjectStorage


def get_object_storage(request: Request) -> ObjectStorage:
    object_storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    if object_storage is None:
        raise RuntimeError("Object storage is not configured")
    return object_storage


__all__ = ["get_object_storage"]
