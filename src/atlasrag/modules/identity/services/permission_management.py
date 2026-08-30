from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from atlasrag.contracts.identity import PermissionManagementUnitOfWork
from atlasrag.contracts.types.identity_types import (
    ActivePermissionGrant,
    PermissionDefinitionState,
)
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.helpers.errors import (
    PermissionGrantConflict,
    PermissionGrantNotFound,
    PermissionNotFound,
    PermissionTargetInactive,
    PermissionTargetNotFound,
    PermissionTargetRetired,
    ProtectedSuperadminRole,
)
from atlasrag.modules.identity.services.superadmin_policy import SuperadminPolicy


class PermissionManagementService:
    def __init__(
        self,
        uow_factory: Callable[[], PermissionManagementUnitOfWork],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_permissions(self) -> tuple[PermissionDefinitionState, ...]:
        async with self._uow_factory() as uow:
            return await uow.permissions.list_permissions()

    async def list_principal_permissions(
        self,
        *,
        principal_id: UUID,
    ) -> tuple[ActivePermissionGrant, ...]:
        async with self._uow_factory() as uow:
            principal = await uow.principals.find_by_id(principal_id)
            if principal is None:
                raise PermissionTargetNotFound(principal_id=principal_id)
            return await uow.permissions.list_active_for_principal(
                principal_id=principal_id,
            )

    async def grant_permission(
        self,
        *,
        principal_id: UUID,
        permission: Permission,
        actor_principal_id: UUID,
    ) -> None:
        try:
            async with self._uow_factory() as uow:
                principal = await uow.principals.find_by_id(principal_id)
                if principal is None:
                    raise PermissionTargetNotFound(principal_id=principal_id)
                if principal.deleted_at is not None:
                    raise PermissionTargetRetired(principal_id=principal_id)
                if not principal.is_active:
                    raise PermissionTargetInactive(principal_id=principal_id)

                await self._ensure_registered(uow, permission)
                if await uow.permissions.has_active_grant(
                    principal_id=principal_id,
                    permission=permission,
                ):
                    raise PermissionGrantConflict(
                        principal_id=principal_id,
                        permission=permission,
                    )

                await uow.permissions.add_grant(
                    principal_id=principal_id,
                    permission=permission,
                    granted_by_principal_id=actor_principal_id,
                    granted_at=self._clock(),
                )
                await uow.commit()
        except IntegrityError as error:
            raise PermissionGrantConflict(
                principal_id=principal_id,
                permission=permission,
            ) from error

    async def revoke_permission(
        self,
        *,
        principal_id: UUID,
        permission: Permission,
        actor_principal_id: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            await self._ensure_registered(uow, permission)

            policy = SuperadminPolicy(uow.superadmins)
            if await policy.is_superadmin_role(principal_id):
                raise ProtectedSuperadminRole(
                    operation=f"revoke {permission.value}",
                )

            revoked = await uow.permissions.revoke_active_grant(
                principal_id=principal_id,
                permission=permission,
                revoked_by_principal_id=actor_principal_id,
                revoked_at=self._clock(),
            )
            if not revoked:
                raise PermissionGrantNotFound(
                    principal_id=principal_id,
                    permission=permission,
                )

            await uow.commit()

    @staticmethod
    async def _ensure_registered(
        uow: PermissionManagementUnitOfWork,
        permission: Permission,
    ) -> None:
        if not await uow.permissions.permission_exists(permission):
            raise PermissionNotFound(permission=permission)
