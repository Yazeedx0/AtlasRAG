import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types.authorization_types import DocumentPermission
from atlasrag.modules.knowledge.models import Document, DocumentACL


class DocumentAccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_active_read_grant(
        self,
        *,
        document_id: uuid.UUID,
        principal_ids: Collection[uuid.UUID],
        at: datetime,
    ) -> bool:
        if not principal_ids:
            return False

        statement = select(
            exists()
            .select_from(DocumentACL)
            .join(Document, Document.id == DocumentACL.document_id)
            .where(
                Document.id == document_id,
                Document.deleted_at.is_(None),
                DocumentACL.principal_id.in_(principal_ids),
                DocumentACL.permission.in_(
                    (DocumentPermission.READ, DocumentPermission.MANAGE)
                ),
                DocumentACL.granted_at <= at,
                DocumentACL.revoked_at.is_(None),
                or_(
                    DocumentACL.expires_at.is_(None),
                    DocumentACL.expires_at > at,
                ),
            )
        )

        return bool(await self._session.scalar(statement))
