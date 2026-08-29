from enum import StrEnum


class DocumentPermission(StrEnum):
    READ = "read"
    MANAGE = "manage"
    MANAGE= "manage"


__all__ = ["DocumentPermission"]
