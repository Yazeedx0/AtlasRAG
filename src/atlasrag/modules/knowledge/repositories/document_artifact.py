from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types.authorization_types import DocumentArtifactStatus
from atlasrag.contracts.error.document_errors import (
    DocumentArtifactConflict,
    DocumentArtifactStorageLocationConflict,
)
from atlasrag.contracts.documents import CreateDocumentArtifact, DocumentArtifactState
from atlasrag.modules.knowledge.models import DocumentArtifact
from atlasrag.platform.database.integrity import is_integrity_error_for_constraint

_DOCUMENT_ARTIFACT_KEY_CONSTRAINT = "uq_document_artifacts_version_artifact_key"
_DOCUMENT_ARTIFACT_STORAGE_LOCATION_CONSTRAINT = "uq_document_artifacts_storage_location"


class DocumentArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
        lock: bool,
    ) -> DocumentArtifactState | None:
        statement = select(*_artifact_columns()).where(
            DocumentArtifact.id == artifact_id,
            DocumentArtifact.document_version_id == document_version_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).one_or_none()
        return _to_artifact_state(row) if row is not None else None

    async def find_by_version_and_key(
        self,
        *,
        document_version_id: UUID,
        artifact_key: str,
    ) -> DocumentArtifactState | None:
        statement = select(*_artifact_columns()).where(
            DocumentArtifact.document_version_id == document_version_id,
            DocumentArtifact.artifact_key == artifact_key,
        )
        row = (await self._session.execute(statement)).one_or_none()
        return _to_artifact_state(row) if row is not None else None

    async def list_for_version(
        self,
        *,
        document_version_id: UUID,
    ) -> tuple[DocumentArtifactState, ...]:
        statement = (
            select(*_artifact_columns())
            .where(DocumentArtifact.document_version_id == document_version_id)
            .order_by(DocumentArtifact.created_at, DocumentArtifact.id)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(_to_artifact_state(row) for row in rows)

    async def create(self, *, artifact: CreateDocumentArtifact) -> DocumentArtifactState:
        statement = insert(DocumentArtifact).values(
            id=artifact.artifact_id,
            document_version_id=artifact.document_version_id,
            artifact_key=artifact.artifact_key,
            language_code=artifact.language_code,
            source_name=artifact.source_name,
            source_uri=artifact.source_uri,
            source_updated_at=artifact.source_updated_at,
            storage_provider=artifact.storage_provider,
            storage_key=artifact.storage_key,
            mime_type=artifact.mime_type,
            file_hash=artifact.file_hash,
            file_size_bytes=artifact.file_size_bytes,
            status=DocumentArtifactStatus.AVAILABLE,
            created_by_principal_id=artifact.created_by_principal_id,
            metadata_=artifact.metadata,
            created_at=artifact.created_at,
            updated_at=artifact.created_at,
        ).returning(*_artifact_columns())
        try:
            row = (await self._session.execute(statement)).one()
        except IntegrityError as error:
            if is_integrity_error_for_constraint(
                error=error,
                constraint_name=_DOCUMENT_ARTIFACT_KEY_CONSTRAINT,
            ):
                raise DocumentArtifactConflict(
                    document_version_id=artifact.document_version_id,
                    artifact_key=artifact.artifact_key,
                ) from error
            if is_integrity_error_for_constraint(
                error=error,
                constraint_name=_DOCUMENT_ARTIFACT_STORAGE_LOCATION_CONSTRAINT,
            ):
                raise DocumentArtifactStorageLocationConflict(
                    storage_provider=artifact.storage_provider,
                    storage_key=artifact.storage_key,
                ) from error
            raise
        return _to_artifact_state(row)

    async def set_status(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
        status: DocumentArtifactStatus,
        updated_at: datetime,
        retired_at: datetime | None,
        deleted_at: datetime | None,
    ) -> DocumentArtifactState | None:
        statement = (
            update(DocumentArtifact)
            .where(
                DocumentArtifact.id == artifact_id,
                DocumentArtifact.document_version_id == document_version_id,
            )
            .values(
                status=status,
                updated_at=updated_at,
                retired_at=retired_at,
                deleted_at=deleted_at,
            )
            .returning(*_artifact_columns())
        )
        row = (await self._session.execute(statement)).one_or_none()
        return _to_artifact_state(row) if row is not None else None


def _artifact_columns() -> tuple[object, ...]:
    return (
        DocumentArtifact.id,
        DocumentArtifact.document_version_id,
        DocumentArtifact.artifact_key,
        DocumentArtifact.language_code,
        DocumentArtifact.source_name,
        DocumentArtifact.source_uri,
        DocumentArtifact.source_updated_at,
        DocumentArtifact.storage_provider,
        DocumentArtifact.storage_key,
        DocumentArtifact.mime_type,
        DocumentArtifact.file_hash,
        DocumentArtifact.file_size_bytes,
        DocumentArtifact.status,
        DocumentArtifact.created_by_principal_id,
        DocumentArtifact.metadata_,
        DocumentArtifact.created_at,
        DocumentArtifact.updated_at,
        DocumentArtifact.retired_at,
        DocumentArtifact.deleted_at,
    )


def _to_artifact_state(row: Row[tuple[object, ...]]) -> DocumentArtifactState:
    return DocumentArtifactState(
        artifact_id=cast(UUID, row.id),
        document_version_id=cast(UUID, row.document_version_id),
        artifact_key=cast(str, row.artifact_key),
        language_code=cast(str, row.language_code),
        source_name=cast(str, row.source_name),
        source_uri=cast("str | None", row.source_uri),
        source_updated_at=cast("datetime | None", row.source_updated_at),
        storage_provider=cast(str, row.storage_provider),
        storage_key=cast(str, row.storage_key),
        mime_type=cast(str, row.mime_type),
        file_hash=cast(str, row.file_hash),
        file_size_bytes=cast(int, row.file_size_bytes),
        status=cast(DocumentArtifactStatus, row.status),
        created_by_principal_id=cast("UUID | None", row.created_by_principal_id),
        metadata=cast(dict[str, object], row.metadata_),
        created_at=cast(datetime, row.created_at),
        updated_at=cast(datetime, row.updated_at),
        retired_at=cast("datetime | None", row.retired_at),
        deleted_at=cast("datetime | None", row.deleted_at),
    )
