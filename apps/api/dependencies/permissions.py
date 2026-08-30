from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status

from apps.api.dependencies.identity import DatabaseSession, get_local_principal_id
from atlasrag.contracts.permission_errors import PermissionDenied
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.repositories.effective_principal import (
    SqlAlchemyEffectivePrincipalRepository,
)
from atlasrag.modules.identity.repositories.permission_repository import (
    SqlAlchemyPermissionRepository,
)
from atlasrag.modules.identity.services.effective_principal_resolver import (
    EffectivePrincipalResolver,
)
from atlasrag.modules.identity.services.permission_authorization import (
    PermissionAuthorizationService,
)

PermissionDependency = Callable[..., Awaitable[UUID]]


def get_permission_authorization_service(
    session: DatabaseSession,
) -> PermissionAuthorizationService:
    return PermissionAuthorizationService(
        effective_principal_resolver=EffectivePrincipalResolver(
            SqlAlchemyEffectivePrincipalRepository(session)
        ),
        permission_repository=SqlAlchemyPermissionRepository(session),
    )


def require_permission(permission: Permission) -> PermissionDependency:
    async def dependency(
        user_principal_id: Annotated[UUID, Depends(get_local_principal_id)],
        authorization_service: Annotated[
            PermissionAuthorizationService,
            Depends(get_permission_authorization_service),
        ],
    ) -> UUID:
        try:
            await authorization_service.require(
                user_principal_id=user_principal_id,
                permission=permission,
            )
        except PermissionDenied:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            ) from None

        return user_principal_id

    return dependency


__all__ = [
    "get_permission_authorization_service",
    "require_permission",
]
