from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from atlasrag.contracts.document_errors import (
    DocumentCanonicalKeyConflict,
    DocumentNotFound,
)
from atlasrag.contracts.documents import (
    CreateDocument,
    DocumentPatch,
    DocumentState,
    KnowledgeUnitOfWork,
)


class DocumentManagementService:
    def __init__(
        self,
        uow_factory: Callable[[], KnowledgeUnitOfWork],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create_document(
        self,
        *,
        canonical_key: str,
        title: str,
        actor_principal_id: UUID,
        description: str | None,
        document_type: str | None,
        department: str | None,
        default_language_code: str | None,
        metadata: dict[str, object],
    ) -> DocumentState:
        created_at = self._clock()
        document = CreateDocument(
            document_id=uuid4(),
            created_by_principal_id=actor_principal_id,
            canonical_key=canonical_key,
            title=title,
            description=description,
            document_type=document_type,
            department=department,
            default_language_code=default_language_code,
            metadata=metadata,
            created_at=created_at,
            updated_at=created_at,
        )
        async with self._uow_factory() as uow:
            if await uow.documents.canonical_key_exists(canonical_key=canonical_key):
                raise DocumentCanonicalKeyConflict(canonical_key=canonical_key)
            created = await uow.documents.create(document=document)
            await uow.commit()
            return created

    async def update_document(
        self,
        *,
        document_id: UUID,
        patch: DocumentPatch,
    ) -> DocumentState:
        async with self._uow_factory() as uow:
            updated = await uow.documents.update_active(
                document_id=document_id,
                patch=patch,
                updated_at=self._clock(),
            )
            if updated is None:
                raise DocumentNotFound(document_id=document_id)
            await uow.commit()
            return updated

    async def delete_document(self, *, document_id: UUID) -> None:
        async with self._uow_factory() as uow:
            deleted = await uow.documents.soft_delete(
                document_id=document_id,
                deleted_at=self._clock(),
            )
            if not deleted:
                raise DocumentNotFound(document_id=document_id)
            await uow.commit()
