from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from atlasrag.contracts.types.authorization_types import DocumentVersionStatus
from atlasrag.contracts.error.document_errors import (
    DocumentVersionDocumentNotFound,
    DocumentVersionInvalidEffectiveRange,
    DocumentVersionInvalidTransition,
    DocumentVersionNotFound,
)
from atlasrag.contracts.documents import (
    CreateDocumentVersion,
    DocumentVersionState,
    KnowledgeUnitOfWork,
)


class DocumentVersionManagementService:
    def __init__(
        self,
        uow_factory: Callable[[], KnowledgeUnitOfWork],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create_version(
        self,
        *,
        document_id: UUID,
        version_label: str,
        actor_principal_id: UUID | None,
        metadata: dict[str, object],
    ) -> DocumentVersionState:
        created_at = self._clock()
        async with self._uow_factory() as uow:
            await self._require_active_document(uow, document_id=document_id)
            created = await uow.document_versions.create(
                version=CreateDocumentVersion(
                    version_id=uuid4(),
                    document_id=document_id,
                    version_label=version_label,
                    created_by_principal_id=actor_principal_id,
                    metadata=metadata,
                    created_at=created_at,
                ),
            )
            await uow.commit()
            return created

    async def publish_version(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        effective_from: datetime,
    ) -> DocumentVersionState:
        published_at = self._clock()
        async with self._uow_factory() as uow:
            version = await uow.document_versions.find_by_id(
                document_id=document_id,
                version_id=version_id,
                lock=True,
            )
            if version is None:
                raise DocumentVersionNotFound(document_id=document_id, version_id=version_id)
            if version.status is not DocumentVersionStatus.DRAFT:
                raise DocumentVersionInvalidTransition(
                    document_id=document_id,
                    version_id=version_id,
                    current_status=version.status,
                    target_status=DocumentVersionStatus.PUBLISHED,
                )

            open_version = await uow.document_versions.find_open_effective_version(
                document_id=document_id,
                lock=True,
            )
            if open_version is not None:
                if open_version.effective_from is not None and (
                    effective_from <= open_version.effective_from
                ):
                    raise DocumentVersionInvalidEffectiveRange(
                        effective_from=open_version.effective_from,
                        effective_to=effective_from,
                    )
                await uow.document_versions.close_effective_period(
                    document_id=document_id,
                    version_id=open_version.version_id,
                    effective_to=effective_from,
                    updated_at=published_at,
                )

            updated = await uow.document_versions.set_published(
                document_id=document_id,
                version_id=version_id,
                published_at=published_at,
                effective_from=effective_from,
                updated_at=published_at,
            )
            if updated is None:
                raise DocumentVersionNotFound(document_id=document_id, version_id=version_id)
            await uow.commit()
            return updated

    async def withdraw_version(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        effective_to: datetime,
    ) -> DocumentVersionState:
        async with self._uow_factory() as uow:
            version = await uow.document_versions.find_by_id(
                document_id=document_id,
                version_id=version_id,
                lock=True,
            )
            if version is None:
                raise DocumentVersionNotFound(document_id=document_id, version_id=version_id)
            if version.status is not DocumentVersionStatus.PUBLISHED:
                raise DocumentVersionInvalidTransition(
                    document_id=document_id,
                    version_id=version_id,
                    current_status=version.status,
                    target_status=DocumentVersionStatus.WITHDRAWN,
                )
            if version.effective_from is not None and effective_to <= version.effective_from:
                raise DocumentVersionInvalidEffectiveRange(
                    effective_from=version.effective_from,
                    effective_to=effective_to,
                )

            updated = await uow.document_versions.set_withdrawn(
                document_id=document_id,
                version_id=version_id,
                effective_to=effective_to,
                updated_at=self._clock(),
            )
            if updated is None:
                raise DocumentVersionNotFound(document_id=document_id, version_id=version_id)
            await uow.commit()
            return updated

    async def archive_version(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentVersionState:
        async with self._uow_factory() as uow:
            version = await uow.document_versions.find_by_id(
                document_id=document_id,
                version_id=version_id,
                lock=True,
            )
            if version is None:
                raise DocumentVersionNotFound(document_id=document_id, version_id=version_id)
            if version.status is not DocumentVersionStatus.WITHDRAWN:
                raise DocumentVersionInvalidTransition(
                    document_id=document_id,
                    version_id=version_id,
                    current_status=version.status,
                    target_status=DocumentVersionStatus.ARCHIVED,
                )

            updated = await uow.document_versions.set_archived(
                document_id=document_id,
                version_id=version_id,
                updated_at=self._clock(),
            )
            if updated is None:
                raise DocumentVersionNotFound(document_id=document_id, version_id=version_id)
            await uow.commit()
            return updated

    async def get_version(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentVersionState:
        async with self._uow_factory() as uow:
            version = await uow.document_versions.find_by_id(
                document_id=document_id,
                version_id=version_id,
                lock=False,
            )
            if version is None:
                raise DocumentVersionNotFound(document_id=document_id, version_id=version_id)
            return version

    async def list_versions(
        self,
        *,
        document_id: UUID,
    ) -> tuple[DocumentVersionState, ...]:
        async with self._uow_factory() as uow:
            await self._require_active_document(uow, document_id=document_id)
            return await uow.document_versions.list_for_document(document_id=document_id)

    async def get_effective_version(
        self,
        *,
        document_id: UUID,
        at: datetime | None,
    ) -> DocumentVersionState | None:
        effective_at = at if at is not None else self._clock()
        async with self._uow_factory() as uow:
            await self._require_active_document(uow, document_id=document_id)
            return await uow.document_versions.find_effective_at(
                document_id=document_id,
                at=effective_at,
            )

    @staticmethod
    async def _require_active_document(
        uow: KnowledgeUnitOfWork,
        *,
        document_id: UUID,
    ) -> None:
        document = await uow.documents.find_active_by_id(document_id=document_id, lock=False)
        if document is None:
            raise DocumentVersionDocumentNotFound(document_id=document_id)
