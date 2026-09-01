from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from atlasrag.contracts.identity import PrincipalRepository
from atlasrag.contracts.types.authorization_types import (
    DocumentArtifactStatus,
    DocumentPermission,
)
from atlasrag.contracts.types.document_types import (
    CreateDocument,
    CreateDocumentAclGrant,
    CreateDocumentArtifact,
    CreateDocumentVersion,
    DocumentAclGrantState,
    DocumentArtifactState,
    DocumentField,
    DocumentPatch,
    DocumentState,
    DocumentVersionState,
    UploadDocumentArtifact,
    UploadedDocumentArtifact,
)


class DocumentRepository(Protocol):
    async def canonical_key_exists(self, *, canonical_key: str) -> bool:
        ...

    async def create(self, *, document: CreateDocument) -> DocumentState:
        ...

    async def find_by_id(
        self,
        *,
        document_id: UUID,
        lock: bool,
    ) -> DocumentState | None:
        ...

    async def find_active_by_id(
        self,
        *,
        document_id: UUID,
        lock: bool,
    ) -> DocumentState | None:
        ...

    async def update_active(
        self,
        *,
        document_id: UUID,
        patch: DocumentPatch,
        updated_at: datetime,
    ) -> DocumentState | None:
        ...

    async def soft_delete(
        self,
        *,
        document_id: UUID,
        deleted_at: datetime,
    ) -> bool:
        ...


class DocumentAclRepository(Protocol):
    async def list_for_document(
        self,
        *,
        document_id: UUID,
        at: datetime,
        include_history: bool,
    ) -> tuple[DocumentAclGrantState, ...]:
        ...

    async def has_unrevoked_grant(
        self,
        *,
        document_id: UUID,
        principal_id: UUID,
        permission: DocumentPermission,
    ) -> bool:
        ...

    async def create_grant(
        self,
        *,
        grant: CreateDocumentAclGrant,
    ) -> DocumentAclGrantState:
        ...

    async def revoke_grant(
        self,
        *,
        document_id: UUID,
        grant_id: UUID,
        revoked_at: datetime,
        revoked_by_principal_id: UUID,
    ) -> bool:
        ...


class DocumentVersionRepository(Protocol):
    async def find_by_id(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        lock: bool,
    ) -> DocumentVersionState | None:
        ...

    async def find_by_document_and_label(
        self,
        *,
        document_id: UUID,
        version_label: str,
    ) -> DocumentVersionState | None:
        ...

    async def list_for_document(
        self,
        *,
        document_id: UUID,
    ) -> tuple[DocumentVersionState, ...]:
        ...

    async def find_effective_at(
        self,
        *,
        document_id: UUID,
        at: datetime,
    ) -> DocumentVersionState | None:
        ...

    async def find_open_effective_version(
        self,
        *,
        document_id: UUID,
        lock: bool,
    ) -> DocumentVersionState | None:
        ...

    async def create(self, *, version: CreateDocumentVersion) -> DocumentVersionState:
        ...

    async def set_published(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        published_at: datetime,
        effective_from: datetime,
        updated_at: datetime,
    ) -> DocumentVersionState | None:
        ...

    async def close_effective_period(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        effective_to: datetime,
        updated_at: datetime,
    ) -> None:
        ...

    async def set_withdrawn(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        effective_to: datetime,
        updated_at: datetime,
    ) -> DocumentVersionState | None:
        ...

    async def set_archived(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        updated_at: datetime,
    ) -> DocumentVersionState | None:
        ...


class DocumentArtifactRepository(Protocol):
    async def find_by_id(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
        lock: bool,
    ) -> DocumentArtifactState | None:
        ...

    async def find_by_version_and_key(
        self,
        *,
        document_version_id: UUID,
        artifact_key: str,
    ) -> DocumentArtifactState | None:
        ...

    async def artifact_key_exists(
        self,
        *,
        document_version_id: UUID,
        artifact_key: str,
    ) -> bool:
        ...

    async def storage_key_exists(
        self,
        *,
        storage_provider: str,
        storage_key: str,
    ) -> bool:
        ...

    async def list_for_version(
        self,
        *,
        document_version_id: UUID,
        include_deleted: bool = False,
    ) -> tuple[DocumentArtifactState, ...]:
        ...

    async def add(self, *, artifact: CreateDocumentArtifact) -> DocumentArtifactState:
        ...

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
        ...


class KnowledgeUnitOfWork(Protocol):
    documents: DocumentRepository
    acl: DocumentAclRepository
    document_versions: DocumentVersionRepository
    document_artifacts: DocumentArtifactRepository
    principals: PrincipalRepository

    async def __aenter__(self) -> "KnowledgeUnitOfWork":
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        ...

    async def commit(self) -> None:
        ...


__all__ = [
    "CreateDocument",
    "CreateDocumentAclGrant",
    "CreateDocumentArtifact",
    "CreateDocumentVersion",
    "DocumentAclGrantState",
    "DocumentAclRepository",
    "DocumentArtifactRepository",
    "DocumentArtifactState",
    "DocumentField",
    "DocumentPatch",
    "DocumentRepository",
    "DocumentState",
    "DocumentVersionRepository",
    "DocumentVersionState",
    "KnowledgeUnitOfWork",
    "UploadDocumentArtifact",
    "UploadedDocumentArtifact",
]
