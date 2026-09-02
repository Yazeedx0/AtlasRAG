from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from atlasrag.contracts.types.authorization import (
    DocumentArtifactStatus,
    DocumentPermission,
    DocumentVersionStatus,
)


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


@dataclass(frozen=True, slots=True)
class DocumentArtifactState:
    artifact_id: UUID
    document_version_id: UUID
    artifact_key: str
    language_code: str
    source_name: str
    source_uri: str | None
    source_updated_at: datetime | None
    storage_provider: str
    storage_key: str
    mime_type: str
    file_hash: str
    file_size_bytes: int
    status: DocumentArtifactStatus
    created_by_principal_id: UUID | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
    retired_at: datetime | None
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class CreateDocumentArtifact:
    artifact_id: UUID
    document_version_id: UUID
    artifact_key: str
    language_code: str
    source_name: str
    source_uri: str | None
    source_updated_at: datetime | None
    storage_provider: str
    storage_key: str
    mime_type: str
    file_hash: str
    file_size_bytes: int
    created_by_principal_id: UUID | None
    metadata: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class UploadDocumentArtifact:
    document_id: UUID
    document_version_id: UUID
    artifact_key: str
    language_code: str
    source_name: str
    source_uri: str | None
    content_type: str
    content: bytes
    source_updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UploadedDocumentArtifact:
    artifact_id: UUID
    document_version_id: UUID
    artifact_key: str
    language_code: str
    mime_type: str
    file_hash: str
    file_size_bytes: int

