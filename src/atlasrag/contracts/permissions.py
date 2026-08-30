from enum import StrEnum


class Permission(StrEnum):
    IAM_PRINCIPALS_MANAGE = "iam.principals.manage"
    IAM_ROLES_MANAGE = "iam.roles.manage"
    IAM_GROUPS_MANAGE = "iam.groups.manage"
    IAM_PERMISSIONS_MANAGE = "iam.permissions.manage"
    KNOWLEDGE_DOCUMENTS_MANAGE = "knowledge.documents.manage"
    KNOWLEDGE_DOCUMENT_ACL_MANAGE = "knowledge.document_acl.manage"


ALL_MANAGEMENT_PERMISSIONS: frozenset[Permission] = frozenset(Permission)


__all__ = ["ALL_MANAGEMENT_PERMISSIONS", "Permission"]
