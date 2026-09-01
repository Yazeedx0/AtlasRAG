from collections.abc import Callable
from uuid import UUID

from atlasrag.contracts.documents import DocumentArtifactState, KnowledgeUnitOfWork
from atlasrag.contracts.error.document_errors import (
    DocumentArtifactNotFound,
    DocumentNotFound,
    DocumentVersionNotFound,
)


class DocumentArtifactQueryService:
    def __init__(self, uow_factory: Callable[[], KnowledgeUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def get_artifact(
        self,
        *,
        document_id: UUID,
        document_version_id: UUID,
        artifact_id: UUID,
    ) -> DocumentArtifactState:
        async with self._uow_factory() as uow:
            await self._require_version(
                uow=uow,
                document_id=document_id,
                document_version_id=document_version_id,
            )
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
        document_id: UUID,
        document_version_id: UUID,
    ) -> tuple[DocumentArtifactState, ...]:
        async with self._uow_factory() as uow:
            await self._require_version(
                uow=uow,
                document_id=document_id,
                document_version_id=document_version_id,
            )
            return await uow.document_artifacts.list_for_version(
                document_version_id=document_version_id,
                include_deleted=False,
            )

    async def _require_version(
        self,
        *,
        uow: KnowledgeUnitOfWork,
        document_id: UUID,
        document_version_id: UUID,
    ) -> None:
        document = await uow.documents.find_active_by_id(document_id=document_id, lock=False)
        if document is None:
            raise DocumentNotFound(document_id=document_id)

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


__all__ = ["DocumentArtifactQueryService"]
