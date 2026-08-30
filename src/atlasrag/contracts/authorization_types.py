from enum import Enum, StrEnum


class DocumentPermission(StrEnum):
    READ = "read"
    MANAGE = "manage"


class DocumentVersionStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    ARCHIVED = "archived"


__all__ = ["DocumentPermission", "DocumentVersionStatus"]
