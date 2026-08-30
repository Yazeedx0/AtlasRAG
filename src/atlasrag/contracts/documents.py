from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol
from uuid import UUID

from atlasrag.contracts.authorization_types import DocumentPermission, DocumentVersionStatus
from atlasrag.contracts.identity import PrincipalRepository


class DocumentField(StrEnum):
    TITLE = "title"
    DESCRIPTION = "description"
    DOCUMENT_TYPE = "document_type"
    DEPARTMENT = "department"
    DEFAULT_LANGUAGE_CODE = "default_language_code"
    METADATA = "metadata"


@dataclass(frozen=True, slots=True)
class DocumentState:
    document_id: UUID
    created_by_principal_id: UUID | None
    canonical_key: str
    title: str
    description: str | None
    document_type: str | None
    department: str | None
    default_language_code: str | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class CreateDocument:
    document_id: UUID
    created_by_principal_id: UUID
    canonical_key: str
    title: str
    description: str | None
    document_type: str | None
    department: str | None
    default_language_code: str | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentPatch:
    fields: frozenset[DocumentField]
    title: str | None
    description: str | None
    document_type: str | None
    department: str | None
    default_language_code: str | None
    metadata: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class DocumentAclGrantState:
    grant_id: UUID
    document_id: UUID
    principal_id: UUID
    permission: DocumentPermission
    granted_at: datetime
    granted_by_principal_id: UUID | None
    expires_at: datetime | None
    revoked_at: datetime | None
    revoked_by_principal_id: UUID | None


@dataclass(frozen=True, slots=True)
class CreateDocumentAclGrant:
    document_id: UUID
    principal_id: UUID
    permission: DocumentPermission
    granted_at: datetime
    granted_by_principal_id: UUID
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class DocumentVersionState:
    version_id: UUID
    document_id: UUID
    version_label: str
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None
    status: DocumentVersionStatus
    created_by_principal_id: UUID | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CreateDocumentVersion:
    version_id: UUID
    document_id: UUID
    version_label: str
    created_by_principal_id: UUID | None
    metadata: dict[str, object]
    created_at: datetime


class DocumentRepository(Protocol):
    async def canonical_key_exists(self, *, canonical_key: str) -> bool:
        ...

    async def create(self, *, document: CreateDocument) -> DocumentState:
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


class KnowledgeUnitOfWork(Protocol):
    documents: DocumentRepository
    acl: DocumentAclRepository
    document_versions: DocumentVersionRepository
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
    "CreateDocumentVersion",
    "DocumentAclGrantState",
    "DocumentAclRepository",
    "DocumentField",
    "DocumentPatch",
    "DocumentRepository",
    "DocumentState",
    "DocumentVersionRepository",
    "DocumentVersionState",
    "KnowledgeUnitOfWork",
]
