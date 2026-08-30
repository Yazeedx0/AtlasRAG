from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from atlasrag.contracts.authorization_types import DocumentPermission
from atlasrag.contracts.document_errors import (
    DocumentAclExpirationInvalid,
    DocumentAclGrantConflict,
    DocumentAclGrantNotFound,
    DocumentAclPrincipalNotFound,
    DocumentNotFound,
)
from atlasrag.contracts.documents import (
    CreateDocumentAclGrant,
    DocumentAclGrantState,
    KnowledgeUnitOfWork,
)


class DocumentAclManagementService:
    def __init__(
        self,
        uow_factory: Callable[[], KnowledgeUnitOfWork],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_acl_grants(
        self,
        *,
        document_id: UUID,
        include_history: bool,
    ) -> tuple[DocumentAclGrantState, ...]:
        at = self._clock()
        async with self._uow_factory() as uow:
            await self._require_active_document(
                uow,
                document_id=document_id,
                lock=False,
            )
            return await uow.acl.list_for_document(
                document_id=document_id,
                at=at,
                include_history=include_history,
            )

    async def grant_acl(
        self,
        *,
        document_id: UUID,
        principal_id: UUID,
        permission: DocumentPermission,
        expires_at: datetime | None,
        actor_principal_id: UUID,
    ) -> DocumentAclGrantState:
        granted_at = self._clock()
        if expires_at is not None and expires_at <= granted_at:
            raise DocumentAclExpirationInvalid(
                expires_at=expires_at,
                granted_at=granted_at,
            )

        async with self._uow_factory() as uow:
            await self._require_active_document(
                uow,
                document_id=document_id,
                lock=True,
            )
            principal = await uow.principals.find_by_id(principal_id)
            if principal is None:
                raise DocumentAclPrincipalNotFound(principal_id=principal_id)
            if await uow.acl.has_unrevoked_grant(
                document_id=document_id,
                principal_id=principal_id,
                permission=permission,
            ):
                raise DocumentAclGrantConflict(
                    document_id=document_id,
                    principal_id=principal_id,
                    permission=permission,
                )
            grant = await uow.acl.create_grant(
                grant=CreateDocumentAclGrant(
                    document_id=document_id,
                    principal_id=principal_id,
                    permission=permission,
                    granted_at=granted_at,
                    granted_by_principal_id=actor_principal_id,
                    expires_at=expires_at,
                ),
            )
            await uow.commit()
            return grant

    async def revoke_acl(
        self,
        *,
        document_id: UUID,
        grant_id: UUID,
        actor_principal_id: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            await self._require_active_document(
                uow,
                document_id=document_id,
                lock=True,
            )
            revoked = await uow.acl.revoke_grant(
                document_id=document_id,
                grant_id=grant_id,
                revoked_at=self._clock(),
                revoked_by_principal_id=actor_principal_id,
            )
            if not revoked:
                raise DocumentAclGrantNotFound(
                    document_id=document_id,
                    grant_id=grant_id,
                )
            await uow.commit()

    @staticmethod
    async def _require_active_document(
        uow: KnowledgeUnitOfWork,
        *,
        document_id: UUID,
        lock: bool,
    ) -> None:
        document = await uow.documents.find_active_by_id(
            document_id=document_id,
            lock=lock,
        )
        if document is None:
            raise DocumentNotFound(document_id=document_id)
