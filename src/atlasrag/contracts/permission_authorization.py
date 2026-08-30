from collections.abc import Collection
from datetime import datetime
from typing import Protocol
from uuid import UUID

from atlasrag.contracts.types.identity_types import (
    ActivePermissionGrant,
    PermissionDefinitionState,
)
from atlasrag.contracts.permissions import Permission


class EffectivePrincipalResolver(Protocol):
    async def resolve_effective_principal_ids(
        self,
        user_principal_id: UUID,
    ) -> frozenset[UUID]:
        ...


class PermissionLookupRepository(Protocol):
    async def has_permission(
        self,
        *,
        principal_ids: Collection[UUID],
        permission: Permission,
        at: datetime,
    ) -> bool:
        ...


class PermissionRepository(PermissionLookupRepository, Protocol):
    async def list_permissions(self) -> tuple[PermissionDefinitionState, ...]:
        ...

    async def list_active_for_principal(
        self,
        *,
        principal_id: UUID,
    ) -> tuple[ActivePermissionGrant, ...]:
        ...

    async def permission_exists(self, permission: Permission) -> bool:
        ...

    async def has_active_grant(
        self,
        *,
        principal_id: UUID,
        permission: Permission,
    ) -> bool:
        ...

    async def add_grant(
        self,
        *,
        principal_id: UUID,
        permission: Permission,
        granted_by_principal_id: UUID | None,
        granted_at: datetime,
    ) -> None:
        ...

    async def revoke_active_grant(
        self,
        *,
        principal_id: UUID,
        permission: Permission,
        revoked_by_principal_id: UUID | None,
        revoked_at: datetime,
    ) -> bool:
        ...


class SuperadminRepository(Protocol):
    async def find_superadmin_role_id(self) -> UUID | None:
        ...

    async def lock_superadmin_role(self) -> UUID | None:
        ...

    async def user_has_superadmin_role(self, user_principal_id: UUID) -> bool:
        ...

    async def count_active_superadmins(self, role_principal_id: UUID) -> int:
        ...


class PermissionAuthorizer(Protocol):
    async def is_allowed(
        self,
        *,
        user_principal_id: UUID,
        permission: Permission,
    ) -> bool:
        ...

    async def require(
        self,
        *,
        user_principal_id: UUID,
        permission: Permission,
    ) -> None:
        ...


__all__ = [
    "EffectivePrincipalResolver",
    "PermissionAuthorizer",
    "PermissionLookupRepository",
    "PermissionRepository",
    "SuperadminRepository",
]
