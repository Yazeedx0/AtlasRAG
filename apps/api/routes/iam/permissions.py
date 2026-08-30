from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from apps.api.dependencies.identity import get_permission_management_service
from apps.api.dependencies.permissions import require_permission
from apps.api.schemas.iam.permissions import (
    PermissionResponse,
    PrincipalPermissionResponse,
)
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.services.permission_management import (
    PermissionManagementService,
)

router = APIRouter(prefix="/iam", tags=["permissions"])


@router.get(
    "/permissions",
    response_model=list[PermissionResponse],
    status_code=status.HTTP_200_OK,
)
async def list_permissions(
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_PERMISSIONS_MANAGE)),
    ],
    service: Annotated[
        PermissionManagementService,
        Depends(get_permission_management_service),
    ],
) -> list[PermissionResponse]:
    permissions = await service.list_permissions()
    return [
        PermissionResponse(
            permission_key=permission.permission_key,
            description=permission.description,
        )
        for permission in permissions
    ]


@router.get(
    "/principals/{principal_id}/permissions",
    response_model=list[PrincipalPermissionResponse],
    status_code=status.HTTP_200_OK,
)
async def list_principal_permissions(
    principal_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_PERMISSIONS_MANAGE)),
    ],
    service: Annotated[
        PermissionManagementService,
        Depends(get_permission_management_service),
    ],
) -> list[PrincipalPermissionResponse]:
    grants = await service.list_principal_permissions(principal_id=principal_id)
    return [
        PrincipalPermissionResponse(
            permission_key=grant.permission_key,
            description=grant.description,
            granted_at=grant.granted_at,
            granted_by_principal_id=grant.granted_by_principal_id,
        )
        for grant in grants
    ]


@router.post(
    "/principals/{principal_id}/permissions/{permission_key}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def grant_principal_permission(
    principal_id: UUID,
    permission_key: Permission,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_PERMISSIONS_MANAGE)),
    ],
    service: Annotated[
        PermissionManagementService,
        Depends(get_permission_management_service),
    ],
) -> Response:
    await service.grant_permission(
        principal_id=principal_id,
        permission=permission_key,
        actor_principal_id=actor_principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/principals/{principal_id}/permissions/{permission_key}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_principal_permission(
    principal_id: UUID,
    permission_key: Permission,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_PERMISSIONS_MANAGE)),
    ],
    service: Annotated[
        PermissionManagementService,
        Depends(get_permission_management_service),
    ],
) -> Response:
    await service.revoke_permission(
        principal_id=principal_id,
        permission=permission_key,
        actor_principal_id=actor_principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
