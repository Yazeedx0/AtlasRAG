from datetime import datetime
from uuid import UUID

from atlasrag.contracts.authorization_types import DocumentPermission


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


__all__ = [
    "DocumentAclExpirationInvalid",
    "DocumentAclGrantConflict",
    "DocumentAclGrantNotFound",
    "DocumentAclPrincipalNotFound",
    "DocumentCanonicalKeyConflict",
    "DocumentError",
    "DocumentNotFound",
]
