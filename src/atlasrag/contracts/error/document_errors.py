from datetime import datetime
from uuid import UUID

from atlasrag.contracts.types.authorization_types import (
    DocumentArtifactStatus,
    DocumentPermission,
    DocumentVersionStatus,
)


class DocumentError(Exception):
    """Base error for document and document ACL management."""


class DocumentNotFound(DocumentError):
    def __init__(self, *, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"document {document_id} not found")


class DocumentDeleted(DocumentError):
    def __init__(self, *, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"document {document_id} is deleted")


class DocumentCanonicalKeyConflict(DocumentError):
    def __init__(self, *, canonical_key: str) -> None:
        self.canonical_key = canonical_key
        super().__init__(f"document canonical key {canonical_key!r} already exists")


class DocumentAclGrantConflict(DocumentError):
    def __init__(
        self,
        *,
        document_id: UUID,
        principal_id: UUID,
        permission: DocumentPermission,
    ) -> None:
        self.document_id = document_id
        self.principal_id = principal_id
        self.permission = permission
        super().__init__(
            "an unrevoked document ACL grant already exists for "
            f"document {document_id}, principal {principal_id}, and permission {permission.value}"
        )


class DocumentAclGrantNotFound(DocumentError):
    def __init__(self, *, document_id: UUID, grant_id: UUID) -> None:
        self.document_id = document_id
        self.grant_id = grant_id
        super().__init__(f"document ACL grant {grant_id} not found for document {document_id}")


class DocumentAclPrincipalNotFound(DocumentError):
    def __init__(self, *, principal_id: UUID) -> None:
        self.principal_id = principal_id
        super().__init__(f"document ACL principal {principal_id} not found")


class DocumentAclExpirationInvalid(DocumentError):
    def __init__(self, *, expires_at: datetime, granted_at: datetime) -> None:
        self.expires_at = expires_at
        self.granted_at = granted_at
        super().__init__("document ACL expiry must be later than the grant time")


class DocumentVersionNotFound(DocumentError):
    def __init__(self, *, document_id: UUID, version_id: UUID) -> None:
        self.document_id = document_id
        self.version_id = version_id
        super().__init__(f"document version {version_id} not found for document {document_id}")


class DocumentVersionConflict(DocumentError):
    def __init__(self, *, document_id: UUID, version_label: str) -> None:
        self.document_id = document_id
        self.version_label = version_label
        super().__init__(
            f"document version label {version_label!r} already exists for document {document_id}"
        )


class DocumentVersionInvalidTransition(DocumentError):
    def __init__(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        current_status: DocumentVersionStatus,
        target_status: DocumentVersionStatus,
    ) -> None:
        self.document_id = document_id
        self.version_id = version_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"document version {version_id} cannot transition from "
            f"{current_status.value} to {target_status.value}"
        )


class DocumentVersionOverlap(DocumentError):
    def __init__(self, *, document_id: UUID, version_id: UUID) -> None:
        self.document_id = document_id
        self.version_id = version_id
        super().__init__(
            f"document version {version_id} overlaps another effective version "
            f"for document {document_id}"
        )


class DocumentVersionInvalidEffectiveRange(DocumentError):
    def __init__(self, *, effective_from: datetime, effective_to: datetime | None) -> None:
        self.effective_from = effective_from
        self.effective_to = effective_to
        super().__init__("document version effective_to must be later than effective_from")


class DocumentVersionDocumentNotFound(DocumentError):
    def __init__(self, *, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"document {document_id} not found")


class DocumentArtifactNotFound(DocumentError):
    def __init__(self, *, document_version_id: UUID, artifact_id: UUID) -> None:
        self.document_version_id = document_version_id
        self.artifact_id = artifact_id
        super().__init__(
            f"document artifact {artifact_id} not found for document version {document_version_id}"
        )


class DocumentArtifactConflict(DocumentError):
    def __init__(self, *, document_version_id: UUID, artifact_key: str) -> None:
        self.document_version_id = document_version_id
        self.artifact_key = artifact_key
        super().__init__(
            f"artifact key {artifact_key!r} already exists for "
            f"document version {document_version_id}"
        )


class DocumentArtifactEmpty(DocumentError):
    def __init__(self) -> None:
        super().__init__("document artifact content must not be empty")


class DocumentArtifactTooLarge(DocumentError):
    def __init__(self, *, file_size_bytes: int, max_file_size_bytes: int) -> None:
        self.file_size_bytes = file_size_bytes
        self.max_file_size_bytes = max_file_size_bytes
        super().__init__(
            f"document artifact size {file_size_bytes} exceeds the "
            f"{max_file_size_bytes} byte limit"
        )


class DocumentArtifactKeyInvalid(DocumentError):
    def __init__(self, *, artifact_key: str) -> None:
        self.artifact_key = artifact_key
        super().__init__(
            "document artifact key must be non-empty after trimming and at most 255 characters"
        )


class DocumentArtifactLanguageCodeInvalid(DocumentError):
    def __init__(self, *, language_code: str) -> None:
        self.language_code = language_code
        super().__init__(f"document artifact language code {language_code!r} is not accepted")


class DocumentArtifactContentTypeInvalid(DocumentError):
    def __init__(self, *, content_type: str) -> None:
        self.content_type = content_type
        super().__init__(f"document artifact content type {content_type!r} is not allowed")


class DocumentArtifactStorageLocationConflict(DocumentError):
    def __init__(self, *, storage_provider: str, storage_key: str) -> None:
        self.storage_provider = storage_provider
        self.storage_key = storage_key
        super().__init__(
            f"storage location {storage_provider}:{storage_key} is already used by another artifact"
        )


class DocumentArtifactVersionNotDraft(DocumentError):
    def __init__(self, *, document_version_id: UUID, status: DocumentVersionStatus) -> None:
        self.document_version_id = document_version_id
        self.status = status
        super().__init__(
            f"document version {document_version_id} is {status.value}; "
            "artifacts can only be added to a draft version"
        )


class DocumentArtifactInvalidTransition(DocumentError):
    def __init__(
        self,
        *,
        artifact_id: UUID,
        current_status: DocumentArtifactStatus,
        target_status: DocumentArtifactStatus,
    ) -> None:
        self.artifact_id = artifact_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"document artifact {artifact_id} cannot transition from "
            f"{current_status.value} to {target_status.value}"
        )


__all__ = [
    "DocumentAclExpirationInvalid",
    "DocumentAclGrantConflict",
    "DocumentAclGrantNotFound",
    "DocumentAclPrincipalNotFound",
    "DocumentArtifactContentTypeInvalid",
    "DocumentArtifactConflict",
    "DocumentArtifactEmpty",
    "DocumentArtifactInvalidTransition",
    "DocumentArtifactKeyInvalid",
    "DocumentArtifactLanguageCodeInvalid",
    "DocumentArtifactNotFound",
    "DocumentArtifactStorageLocationConflict",
    "DocumentArtifactTooLarge",
    "DocumentArtifactVersionNotDraft",
    "DocumentCanonicalKeyConflict",
    "DocumentDeleted",
    "DocumentError",
    "DocumentNotFound",
    "DocumentVersionConflict",
    "DocumentVersionDocumentNotFound",
    "DocumentVersionInvalidEffectiveRange",
    "DocumentVersionInvalidTransition",
    "DocumentVersionNotFound",
    "DocumentVersionOverlap",
]
