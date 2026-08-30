from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, insert, select, update
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from atlasrag.contracts.documents import (
    CreateDocument,
    DocumentField,
    DocumentPatch,
    DocumentState,
)
from atlasrag.contracts.error.document_errors import DocumentCanonicalKeyConflict
from atlasrag.modules.knowledge.models import Document
from atlasrag.platform.database.integrity import is_integrity_error_for_constraint

_DOCUMENT_CANONICAL_KEY_CONSTRAINT = "uq_documents_canonical_key"


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def canonical_key_exists(self, *, canonical_key: str) -> bool:
        statement = select(
            exists().where(Document.canonical_key == canonical_key),
        )
        return bool(await self._session.scalar(statement))

    async def create(self, *, document: CreateDocument) -> DocumentState:
        statement = insert(Document).values(
            id=document.document_id,
            created_by_principal_id=document.created_by_principal_id,
            canonical_key=document.canonical_key,
            title=document.title,
            description=document.description,
            document_type=document.document_type,
            department=document.department,
            default_language_code=document.default_language_code,
            metadata_=document.metadata,
            created_at=document.created_at,
            updated_at=document.updated_at,
            deleted_at=None,
        ).returning(*_document_columns())
        try:
            row = (await self._session.execute(statement)).one()
        except IntegrityError as error:
            if is_integrity_error_for_constraint(
                error=error,
                constraint_name=_DOCUMENT_CANONICAL_KEY_CONSTRAINT,
            ):
                raise DocumentCanonicalKeyConflict(
                    canonical_key=document.canonical_key,
                ) from error
            raise
        return _to_document_state(row)

    async def find_by_id(
        self,
        *,
        document_id: UUID,
        lock: bool,
    ) -> DocumentState | None:
        statement = select(*_document_columns()).where(Document.id == document_id)
        if lock:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).one_or_none()
        return _to_document_state(row) if row is not None else None

    async def find_active_by_id(
        self,
        *,
        document_id: UUID,
        lock: bool,
    ) -> DocumentState | None:
        statement = select(*_document_columns()).where(
            Document.id == document_id,
            Document.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).one_or_none()
        return _to_document_state(row) if row is not None else None

    async def update_active(
        self,
        *,
        document_id: UUID,
        patch: DocumentPatch,
        updated_at: datetime,
    ) -> DocumentState | None:
        values: dict[str, object] = {"updated_at": updated_at}
        if DocumentField.TITLE in patch.fields:
            values["title"] = patch.title
        if DocumentField.DESCRIPTION in patch.fields:
            values["description"] = patch.description
        if DocumentField.DOCUMENT_TYPE in patch.fields:
            values["document_type"] = patch.document_type
        if DocumentField.DEPARTMENT in patch.fields:
            values["department"] = patch.department
        if DocumentField.DEFAULT_LANGUAGE_CODE in patch.fields:
            values["default_language_code"] = patch.default_language_code
        if DocumentField.METADATA in patch.fields:
            values["metadata_"] = patch.metadata

        statement = (
            update(Document)
            .where(
                Document.id == document_id,
                Document.deleted_at.is_(None),
            )
            .values(**values)
            .returning(*_document_columns())
        )
        row = (await self._session.execute(statement)).one_or_none()
        return _to_document_state(row) if row is not None else None

    async def soft_delete(
        self,
        *,
        document_id: UUID,
        deleted_at: datetime,
    ) -> bool:
        statement = (
            update(Document)
            .where(
                Document.id == document_id,
                Document.deleted_at.is_(None),
            )
            .values(
                deleted_at=deleted_at,
                updated_at=deleted_at,
            )
            .returning(Document.id)
        )
        return (await self._session.scalar(statement)) is not None


def _document_columns() -> tuple[InstrumentedAttribute, ...]:
    return (
        Document.id,
        Document.created_by_principal_id,
        Document.canonical_key,
        Document.title,
        Document.description,
        Document.document_type,
        Document.department,
        Document.default_language_code,
        Document.metadata_,
        Document.created_at,
        Document.updated_at,
        Document.deleted_at,
    )


def _to_document_state(row: Row) -> DocumentState:
    return DocumentState(
        document_id=row.id,
        created_by_principal_id=row.created_by_principal_id,
        canonical_key=row.canonical_key,
        title=row.title,
        description=row.description,
        document_type=row.document_type,
        department=row.department,
        default_language_code=row.default_language_code,
        metadata=row.metadata_,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )
