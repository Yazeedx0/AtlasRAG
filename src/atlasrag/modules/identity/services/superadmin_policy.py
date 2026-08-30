from uuid import UUID

from atlasrag.contracts.permission_authorization import SuperadminRepository
from atlasrag.modules.identity.helpers.errors import (
    LastSuperadminViolation,
    ProtectedSuperadminRole,
)


class SuperadminPolicy:
    def __init__(self, repository: SuperadminRepository) -> None:
        self._repository = repository

    async def is_superadmin_role(self, principal_id: UUID) -> bool:
        role_id = await self._repository.find_superadmin_role_id()
        return role_id == principal_id

    async def protect_role_lifecycle(
        self,
        principal_id: UUID,
        *,
        operation: str,
    ) -> None:
        if await self.is_superadmin_role(principal_id):
            raise ProtectedSuperadminRole(operation=operation)

    async def protect_user_removal(
        self,
        user_principal_id: UUID,
        *,
        operation: str,
    ) -> None:
        role_id = await self._repository.lock_superadmin_role()
        if role_id is None:
            raise ProtectedSuperadminRole(operation="validate superadmin invariant")

        if not await self._repository.user_has_superadmin_role(user_principal_id):
            return

        count = await self._repository.count_active_superadmins(role_id)
        if count <= 1:
            raise LastSuperadminViolation(
                user_principal_id=user_principal_id,
                operation=operation,
            )
