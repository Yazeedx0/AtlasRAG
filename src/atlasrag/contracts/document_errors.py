from datetime import datetime
from uuid import UUID

from atlasrag.contracts.authorization_types import DocumentPermission, DocumentVersionStatus


class DocumentError(Exception):
    """Base error for document and document ACL management."""


class DocumentNotFound(DocumentError):
    def __init__(self, *, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"document {document_id} not found")


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


__all__ = [
    "DocumentAclExpirationInvalid",
    "DocumentAclGrantConflict",
    "DocumentAclGrantNotFound",
    "DocumentAclPrincipalNotFound",
    "DocumentCanonicalKeyConflict",
    "DocumentError",
    "DocumentNotFound",
    "DocumentVersionConflict",
    "DocumentVersionDocumentNotFound",
    "DocumentVersionInvalidEffectiveRange",
    "DocumentVersionInvalidTransition",
    "DocumentVersionNotFound",
    "DocumentVersionOverlap",
]
