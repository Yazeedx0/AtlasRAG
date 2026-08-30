from typing import Protocol


class ObjectStorage(Protocol):
    async def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        ...

    async def get(
        self,
        *,
        key: str,
    ) -> bytes:
        ...

    async def delete(
        self,
        *,
        key: str,
    ) -> None:
        ...

    async def exists(
        self,
        *,
        key: str,
    ) -> bool:
        ...


__all__ = ["ObjectStorage"]
