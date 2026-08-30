from enum import Enum


class Permission(Enum):
    IAM_PRINCIPALS_MANAGE = "iam.principals.manage"
    IAM_ROLES_MANAGE = "iam.roles.manage"
    IAM_GROUPS_MANAGE = "iam.groups.manage"
    KNOWLEDGE_DOCUMENT_ACL_MANAGE = "knowledge.document_acl.manage"


__all__ = ["Permission"]
