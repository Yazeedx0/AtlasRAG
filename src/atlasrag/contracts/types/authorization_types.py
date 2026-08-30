from enum import Enum, StrEnum


class DocumentPermission(StrEnum):
    READ = "read"
    MANAGE = "manage"


class DocumentVersionStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    ARCHIVED = "archived"


class DocumentArtifactStatus(Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    RETIRED = "retired"
    DELETED = "deleted"


__all__ = ["DocumentArtifactStatus", "DocumentPermission", "DocumentVersionStatus"]
