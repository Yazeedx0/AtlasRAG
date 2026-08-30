from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from atlasrag.contracts.documents import (
    CreateDocumentArtifact,
    DocumentArtifactState,
    KnowledgeUnitOfWork,
)
from atlasrag.contracts.error.document_errors import (
    DocumentArtifactInvalidTransition,
    DocumentArtifactNotFound,
    DocumentArtifactVersionNotDraft,
    DocumentVersionNotFound,
)
from atlasrag.contracts.types.authorization_types import (
    DocumentArtifactStatus,
    DocumentVersionStatus,
)

_VALID_TRANSITIONS: dict[DocumentArtifactStatus, frozenset[DocumentArtifactStatus]] = {
    DocumentArtifactStatus.AVAILABLE: frozenset(
        {DocumentArtifactStatus.MISSING, DocumentArtifactStatus.RETIRED}
    ),
    DocumentArtifactStatus.MISSING: frozenset(
        {DocumentArtifactStatus.AVAILABLE, DocumentArtifactStatus.RETIRED}
    ),
    DocumentArtifactStatus.RETIRED: frozenset({DocumentArtifactStatus.DELETED}),
    DocumentArtifactStatus.DELETED: frozenset(),
}


class DocumentArtifactManagementService:
    def __init__(
        self,
        uow_factory: Callable[[], KnowledgeUnitOfWork],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create_artifact(
        self,
        *,
        document_id: UUID,
        document_version_id: UUID,
        artifact_key: str,
        language_code: str,
        source_name: str,
        source_uri: str | None,
        source_updated_at: datetime | None,
        storage_provider: str,
        storage_key: str,
        mime_type: str,
        file_hash: str,
        file_size_bytes: int,
        actor_principal_id: UUID | None,
        metadata: dict[str, object],
    ) -> DocumentArtifactState:
        created_at = self._clock()
        async with self._uow_factory() as uow:
            version = await uow.document_versions.find_by_id(
                document_id=document_id,
                version_id=document_version_id,
                lock=False,
            )
            if version is None:
                raise DocumentVersionNotFound(
                    document_id=document_id,
                    version_id=document_version_id,
                )
            if version.status is not DocumentVersionStatus.DRAFT:
                raise DocumentArtifactVersionNotDraft(
                    document_version_id=document_version_id,
                    status=version.status,
                )

            created = await uow.document_artifacts.create(
                artifact=CreateDocumentArtifact(
                    artifact_id=uuid4(),
                    document_version_id=document_version_id,
                    artifact_key=artifact_key,
                    language_code=language_code,
                    source_name=source_name,
                    source_uri=source_uri,
                    source_updated_at=source_updated_at,
                    storage_provider=storage_provider,
                    storage_key=storage_key,
                    mime_type=mime_type,
                    file_hash=file_hash,
                    file_size_bytes=file_size_bytes,
                    created_by_principal_id=actor_principal_id,
                    metadata=metadata,
                    created_at=created_at,
                ),
            )
            await uow.commit()
            return created

    async def mark_missing(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
    ) -> DocumentArtifactState:
        return await self._transition(
            document_version_id=document_version_id,
            artifact_id=artifact_id,
            target_status=DocumentArtifactStatus.MISSING,
        )

    async def mark_available(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
    ) -> DocumentArtifactState:
        return await self._transition(
            document_version_id=document_version_id,
            artifact_id=artifact_id,
            target_status=DocumentArtifactStatus.AVAILABLE,
        )

    async def retire_artifact(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
    ) -> DocumentArtifactState:
        return await self._transition(
            document_version_id=document_version_id,
            artifact_id=artifact_id,
            target_status=DocumentArtifactStatus.RETIRED,
            retired_at=self._clock(),
        )

    async def delete_artifact(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
    ) -> DocumentArtifactState:
        return await self._transition(
            document_version_id=document_version_id,
            artifact_id=artifact_id,
            target_status=DocumentArtifactStatus.DELETED,
            deleted_at=self._clock(),
        )

    async def get_artifact(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
    ) -> DocumentArtifactState:
        async with self._uow_factory() as uow:
            artifact = await uow.document_artifacts.find_by_id(
                document_version_id=document_version_id,
                artifact_id=artifact_id,
                lock=False,
            )
            if artifact is None:
                raise DocumentArtifactNotFound(
                    document_version_id=document_version_id,
                    artifact_id=artifact_id,
                )
            return artifact

    async def list_artifacts(
        self,
        *,
        document_version_id: UUID,
    ) -> tuple[DocumentArtifactState, ...]:
        async with self._uow_factory() as uow:
            return await uow.document_artifacts.list_for_version(
                document_version_id=document_version_id,
            )

    async def _transition(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
        target_status: DocumentArtifactStatus,
        retired_at: datetime | None = None,
        deleted_at: datetime | None = None,
    ) -> DocumentArtifactState:
        async with self._uow_factory() as uow:
            artifact = await uow.document_artifacts.find_by_id(
                document_version_id=document_version_id,
                artifact_id=artifact_id,
                lock=True,
            )
            if artifact is None:
                raise DocumentArtifactNotFound(
                    document_version_id=document_version_id,
                    artifact_id=artifact_id,
                )
            if target_status not in _VALID_TRANSITIONS[artifact.status]:
                raise DocumentArtifactInvalidTransition(
                    artifact_id=artifact_id,
                    current_status=artifact.status,
                    target_status=target_status,
                )

            updated = await uow.document_artifacts.set_status(
                document_version_id=document_version_id,
                artifact_id=artifact_id,
                status=target_status,
                updated_at=self._clock(),
                retired_at=retired_at if retired_at is not None else artifact.retired_at,
                deleted_at=deleted_at if deleted_at is not None else artifact.deleted_at,
            )
            if updated is None:
                raise DocumentArtifactNotFound(
                    document_version_id=document_version_id,
                    artifact_id=artifact_id,
                )
            await uow.commit()
            return updated
