import uuid
from collections.abc import Collection
from datetime import datetime

from atlasrag.contracts.authorization import DocumentAccessRepository


class DocumentAuthorizationService:
    def __init__(
        self,
        repository: DocumentAccessRepository,
    ) -> None:
        self._repository = repository

    async def can_read_document(
        self,
        *,
        document_id: uuid.UUID,
        effective_principal_ids: Collection[uuid.UUID],
        at: datetime,
    ) -> bool:
        if not effective_principal_ids:
            return False

        return await self._repository.has_active_read_grant(
            document_id=document_id,
            principal_ids=effective_principal_ids,
            at=at,
        )
