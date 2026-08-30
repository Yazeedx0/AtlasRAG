from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from atlasrag.contracts.permission_authorization import (
    EffectivePrincipalResolver,
    PermissionLookupRepository,
)
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.helpers.errors import PermissionDenied


class PermissionAuthorizationService:
    def __init__(
        self,
        *,
        effective_principal_resolver: EffectivePrincipalResolver,
        permission_repository: PermissionLookupRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._effective_principal_resolver = effective_principal_resolver
        self._permission_repository = permission_repository
        self._clock = clock or (lambda: datetime.now(UTC))

    async def is_allowed(
        self,
        *,
        user_principal_id: UUID,
        permission: Permission,
    ) -> bool:
        effective_principal_ids = (
            await self._effective_principal_resolver.resolve_effective_principal_ids(
                user_principal_id
            )
        )
        return await self._permission_repository.has_permission(
            principal_ids=effective_principal_ids,
            permission=permission,
            at=self._clock(),
        )

    async def require(
        self,
        *,
        user_principal_id: UUID,
        permission: Permission,
    ) -> None:
        if await self.is_allowed(
            user_principal_id=user_principal_id,
            permission=permission,
        ):
            return

        raise PermissionDenied(
            actor_principal_id=user_principal_id,
            permission=permission,
        )
