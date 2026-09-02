import uuid
from datetime import datetime

from sqlalchemy import exists, insert, or_, select, update
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from atlasrag.contracts.types.authorization import DocumentPermission
from atlasrag.contracts.error.document_errors import DocumentAclGrantConflict
from atlasrag.contracts.documents import CreateDocumentAclGrant, DocumentAclGrantState
from atlasrag.modules.knowledge.models import DocumentACL
from atlasrag.platform.database.integrity import is_integrity_error_for_constraint

_ACTIVE_DOCUMENT_ACL_CONSTRAINT = "uq_document_acl_active_grant"


class DocumentAclRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_document(
        self,
        *,
        document_id: uuid.UUID,
        at: datetime,
        include_history: bool,
    ) -> tuple[DocumentAclGrantState, ...]:
        statement = select(*_acl_columns()).where(DocumentACL.document_id == document_id)
        if not include_history:
            statement = statement.where(
                DocumentACL.granted_at <= at,
                DocumentACL.revoked_at.is_(None),
                or_(
                    DocumentACL.expires_at.is_(None),
                    DocumentACL.expires_at > at,
                ),
            )
        statement = statement.order_by(DocumentACL.granted_at, DocumentACL.id)
        rows = (await self._session.execute(statement)).all()
        return tuple(_to_acl_grant_state(row) for row in rows)

    async def has_unrevoked_grant(
        self,
        *,
        document_id: uuid.UUID,
        principal_id: uuid.UUID,
        permission: DocumentPermission,
    ) -> bool:
        statement = select(
            exists().where(
                DocumentACL.document_id == document_id,
                DocumentACL.principal_id == principal_id,
                DocumentACL.permission == permission,
                DocumentACL.revoked_at.is_(None),
            ),
        )
        return bool(await self._session.scalar(statement))

    async def create_grant(
        self,
        *,
        grant: CreateDocumentAclGrant,
    ) -> DocumentAclGrantState:
        grant_id = uuid.uuid4()
        statement = insert(DocumentACL).values(
            id=grant_id,
            document_id=grant.document_id,
            principal_id=grant.principal_id,
            permission=grant.permission,
            granted_at=grant.granted_at,
            granted_by_principal_id=grant.granted_by_principal_id,
            expires_at=grant.expires_at,
            revoked_at=None,
            revoked_by_principal_id=None,
        ).returning(*_acl_columns())
        try:
            row = (await self._session.execute(statement)).one()
        except IntegrityError as error:
            if is_integrity_error_for_constraint(
                error=error,
                constraint_name=_ACTIVE_DOCUMENT_ACL_CONSTRAINT,
            ):
                raise DocumentAclGrantConflict(
                    document_id=grant.document_id,
                    principal_id=grant.principal_id,
                    permission=grant.permission,
                ) from error
            raise
        return _to_acl_grant_state(row)

    async def revoke_grant(
        self,
        *,
        document_id: uuid.UUID,
        grant_id: uuid.UUID,
        revoked_at: datetime,
        revoked_by_principal_id: uuid.UUID,
    ) -> bool:
        statement = (
            update(DocumentACL)
            .where(
                DocumentACL.document_id == document_id,
                DocumentACL.id == grant_id,
                DocumentACL.revoked_at.is_(None),
            )
            .values(
                revoked_at=revoked_at,
                revoked_by_principal_id=revoked_by_principal_id,
            )
            .returning(DocumentACL.id)
        )
        return (await self._session.scalar(statement)) is not None


def _acl_columns() -> tuple[InstrumentedAttribute, ...]:
    return (
        DocumentACL.id,
        DocumentACL.document_id,
        DocumentACL.principal_id,
        DocumentACL.permission,
        DocumentACL.granted_at,
        DocumentACL.granted_by_principal_id,
        DocumentACL.expires_at,
        DocumentACL.revoked_at,
        DocumentACL.revoked_by_principal_id,
    )


def _to_acl_grant_state(row: Row) -> DocumentAclGrantState:
    return DocumentAclGrantState(
        grant_id=row.id,
        document_id=row.document_id,
        principal_id=row.principal_id,
        permission=row.permission,
        granted_at=row.granted_at,
        granted_by_principal_id=row.granted_by_principal_id,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        revoked_by_principal_id=row.revoked_by_principal_id,
    )
