import uuid
from collections.abc import Collection
from datetime import datetime
from typing import Protocol

from atlasrag.contracts.types.authorization import DocumentPermission


class DocumentAccessRepository(Protocol):
    async def has_active_read_grant(
        self,
        *,
        document_id: uuid.UUID,
        principal_ids: Collection[uuid.UUID],
        at: datetime,
    ) -> bool:
        ...


__all__ = ["DocumentAccessRepository", "DocumentPermission"]
