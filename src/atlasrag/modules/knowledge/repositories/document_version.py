from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import insert, or_, select, update
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.documents import CreateDocumentVersion, DocumentVersionState
from atlasrag.contracts.error.document_errors import DocumentVersionConflict, DocumentVersionOverlap
from atlasrag.contracts.types.authorization_types import DocumentVersionStatus
from atlasrag.modules.knowledge.models import DocumentVersion
from atlasrag.platform.database.integrity import is_integrity_error_for_constraint

_DOCUMENT_VERSION_LABEL_CONSTRAINT = "uq_document_versions_document_id_version_label"
_DOCUMENT_VERSION_OVERLAP_CONSTRAINT = "ex_document_versions_no_overlapping_effective_period"


class DocumentVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        lock: bool,
    ) -> DocumentVersionState | None:
        statement = select(*_version_columns()).where(
            DocumentVersion.id == version_id,
            DocumentVersion.document_id == document_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).one_or_none()
        return _to_version_state(row) if row is not None else None

    async def find_by_document_and_label(
        self,
        *,
        document_id: UUID,
        version_label: str,
    ) -> DocumentVersionState | None:
        statement = select(*_version_columns()).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version_label == version_label,
        )
        row = (await self._session.execute(statement)).one_or_none()
        return _to_version_state(row) if row is not None else None

    async def list_for_document(
        self,
        *,
        document_id: UUID,
    ) -> tuple[DocumentVersionState, ...]:
        statement = (
            select(*_version_columns())
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.created_at, DocumentVersion.id)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(_to_version_state(row) for row in rows)

    async def find_effective_at(
        self,
        *,
        document_id: UUID,
        at: datetime,
    ) -> DocumentVersionState | None:
        statement = select(*_version_columns()).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.effective_from.is_not(None),
            DocumentVersion.effective_from <= at,
            or_(
                DocumentVersion.effective_to.is_(None),
                DocumentVersion.effective_to > at,
            ),
        )
        row = (await self._session.execute(statement)).one_or_none()
        return _to_version_state(row) if row is not None else None

    async def find_open_effective_version(
        self,
        *,
        document_id: UUID,
        lock: bool,
    ) -> DocumentVersionState | None:
        statement = select(*_version_columns()).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.effective_from.is_not(None),
            DocumentVersion.effective_to.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).one_or_none()
        return _to_version_state(row) if row is not None else None

    async def create(self, *, version: CreateDocumentVersion) -> DocumentVersionState:
        statement = insert(DocumentVersion).values(
            id=version.version_id,
            document_id=version.document_id,
            version_label=version.version_label,
            effective_from=None,
            effective_to=None,
            published_at=None,
            status=DocumentVersionStatus.DRAFT,
            created_by_principal_id=version.created_by_principal_id,
            metadata_=version.metadata,
            created_at=version.created_at,
            updated_at=version.created_at,
        ).returning(*_version_columns())
        try:
            row = (await self._session.execute(statement)).one()
        except IntegrityError as error:
            if is_integrity_error_for_constraint(
                error=error,
                constraint_name=_DOCUMENT_VERSION_LABEL_CONSTRAINT,
            ):
                raise DocumentVersionConflict(
                    document_id=version.document_id,
                    version_label=version.version_label,
                ) from error
            raise
        return _to_version_state(row)

    async def set_published(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        published_at: datetime,
        effective_from: datetime,
        updated_at: datetime,
    ) -> DocumentVersionState | None:
        statement = (
            update(DocumentVersion)
            .where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
            .values(
                status=DocumentVersionStatus.PUBLISHED,
                published_at=published_at,
                effective_from=effective_from,
                updated_at=updated_at,
            )
            .returning(*_version_columns())
        )
        try:
            row = (await self._session.execute(statement)).one_or_none()
        except IntegrityError as error:
            if is_integrity_error_for_constraint(
                error=error,
                constraint_name=_DOCUMENT_VERSION_OVERLAP_CONSTRAINT,
            ):
                raise DocumentVersionOverlap(
                    document_id=document_id,
                    version_id=version_id,
                ) from error
            raise
        return _to_version_state(row) if row is not None else None

    async def close_effective_period(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        effective_to: datetime,
        updated_at: datetime,
    ) -> None:
        statement = (
            update(DocumentVersion)
            .where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
            .values(effective_to=effective_to, updated_at=updated_at)
        )
        await self._session.execute(statement)

    async def set_withdrawn(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        effective_to: datetime,
        updated_at: datetime,
    ) -> DocumentVersionState | None:
        statement = (
            update(DocumentVersion)
            .where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
            .values(
                status=DocumentVersionStatus.WITHDRAWN,
                effective_to=effective_to,
                updated_at=updated_at,
            )
            .returning(*_version_columns())
        )
        row = (await self._session.execute(statement)).one_or_none()
        return _to_version_state(row) if row is not None else None

    async def set_archived(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        updated_at: datetime,
    ) -> DocumentVersionState | None:
        statement = (
            update(DocumentVersion)
            .where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
            .values(status=DocumentVersionStatus.ARCHIVED, updated_at=updated_at)
            .returning(*_version_columns())
        )
        row = (await self._session.execute(statement)).one_or_none()
        return _to_version_state(row) if row is not None else None


def _version_columns() -> tuple[object, ...]:
    return (
        DocumentVersion.id,
        DocumentVersion.document_id,
        DocumentVersion.version_label,
        DocumentVersion.effective_from,
        DocumentVersion.effective_to,
        DocumentVersion.published_at,
        DocumentVersion.status,
        DocumentVersion.created_by_principal_id,
        DocumentVersion.metadata_,
        DocumentVersion.created_at,
        DocumentVersion.updated_at,
    )


def _to_version_state(row: Row[tuple[object, ...]]) -> DocumentVersionState:
    return DocumentVersionState(
        version_id=cast(UUID, row.id),
        document_id=cast(UUID, row.document_id),
        version_label=cast(str, row.version_label),
        effective_from=cast("datetime | None", row.effective_from),
        effective_to=cast("datetime | None", row.effective_to),
        published_at=cast("datetime | None", row.published_at),
        status=cast(DocumentVersionStatus, row.status),
        created_by_principal_id=cast("UUID | None", row.created_by_principal_id),
        metadata=cast(dict[str, object], row.metadata_),
        created_at=cast(datetime, row.created_at),
        updated_at=cast(datetime, row.updated_at),
    )
