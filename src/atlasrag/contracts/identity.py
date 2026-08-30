from datetime import datetime
from enum import Enum
from types import TracebackType
from typing import Protocol
from uuid import UUID

from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.identity_types import (
    AssignedRole,
    DirectGroupMember,
    LocalUserIdentity,
    PrincipalState,
)
from atlasrag.contracts.permission_authorization import (
    PermissionRepository,
    SuperadminRepository,
)


class IdentifierType(Enum):
    OIDC_SUBJECT = "oidc_subject"


class IdentityRepository(Protocol):
    async def find_by_oidc_subject(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> LocalUserIdentity | None:
        """Look up a local identity by (identifier_type=oidc_subject, issuer, subject)."""
        ...

    async def provision_user(
        self,
        identity: AuthenticatedIdentity,
    ) -> UUID:
        """Atomically create Principal(type=user), User, and UserIdentifier."""
        ...


class PrincipalRepository(Protocol):
    async def find_by_id(self, principal_id: UUID) -> PrincipalState | None:
        ...

    async def activate(self, principal_id: UUID) -> None:
        ...

    async def deactivate(self, principal_id: UUID) -> None:
        ...

    async def retire(self, principal_id: UUID) -> None:
        ...


class GroupMembershipRepository(Protocol):
    async def list_active_members(
        self,
        *,
        group_principal_id: UUID,
    ) -> tuple[DirectGroupMember, ...]:
        ...

    async def has_active_membership(
        self,
        *,
        group_principal_id: UUID,
        member_principal_id: UUID,
    ) -> bool:
        ...

    async def add_membership(
        self,
        *,
        group_principal_id: UUID,
        member_principal_id: UUID,
        member_type: str,
        added_by_principal_id: UUID,
        added_at: datetime,
    ) -> None:
        ...

    async def close_active_membership(
        self,
        *,
        group_principal_id: UUID,
        member_principal_id: UUID,
        removed_by_principal_id: UUID,
        removed_at: datetime,
    ) -> bool:
        ...

    async def would_create_cycle(
        self,
        *,
        group_principal_id: UUID,
        member_group_principal_id: UUID,
    ) -> bool:
        ...


class EffectivePrincipalRepository(Protocol):
    async def find_effective_principal_ids(
        self,
        user_principal_id: UUID,
    ) -> frozenset[UUID]:
        ...


class UserIdentifierRepository(Protocol):
    async def close_active_for_user(
        self,
        user_principal_id: UUID,
        *,
        closed_at: datetime,
    ) -> None:
        ...


class RoleAssignmentRepository(Protocol):
    async def list_active_for_user(
        self,
        user_principal_id: UUID,
    ) -> tuple[AssignedRole, ...]:
        ...

    async def user_exists(self, user_principal_id: UUID) -> bool:
        ...

    async def role_exists(self, role_principal_id: UUID) -> bool:
        ...

    async def has_active_assignment(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
    ) -> bool:
        ...

    async def add_assignment(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
        assigned_by_principal_id: UUID,
        assigned_at: datetime,
    ) -> None:
        ...

    async def close_active_assignment(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
        revoked_by_principal_id: UUID,
        revoked_at: datetime,
    ) -> bool:
        ...


class IdentityUnitOfWork(Protocol):
    identities: IdentityRepository
    principals: PrincipalRepository

    async def __aenter__(self) -> "IdentityUnitOfWork":
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


class GroupMembershipUnitOfWork(IdentityUnitOfWork, Protocol):
    memberships: GroupMembershipRepository

    async def __aenter__(self) -> "GroupMembershipUnitOfWork":
        ...


class ProtectedIdentityUnitOfWork(IdentityUnitOfWork, Protocol):
    superadmins: SuperadminRepository

    async def __aenter__(self) -> "ProtectedIdentityUnitOfWork":
        ...


class PermissionManagementUnitOfWork(ProtectedIdentityUnitOfWork, Protocol):
    permissions: PermissionRepository

    async def __aenter__(self) -> "PermissionManagementUnitOfWork":
        ...


class RoleAssignmentUnitOfWork(ProtectedIdentityUnitOfWork, Protocol):
    role_assignments: RoleAssignmentRepository

    async def __aenter__(self) -> "RoleAssignmentUnitOfWork":
        ...


class ProvisioningPolicy(Protocol):
    def jit_enabled(self) -> bool:
        ...
