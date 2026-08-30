from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from apps.api.dependencies.identity import get_role_assignment_service
from apps.api.dependencies.permissions import require_permission
from apps.api.schemas.iam.roles import AssignedRoleResponse, AssignRoleRequest
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.services.role_assignment import RoleAssignmentService

router = APIRouter(prefix="/iam/users", tags=["roles"])


@router.get(
    "/{user_id}/roles",
    response_model=list[AssignedRoleResponse],
    status_code=status.HTTP_200_OK,
)
async def list_user_roles(
    user_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_ROLES_MANAGE)),
    ],
    service: Annotated[
        RoleAssignmentService,
        Depends(get_role_assignment_service),
    ],
) -> list[AssignedRoleResponse]:
    assignments = await service.list_roles(user_principal_id=user_id)
    return [
        AssignedRoleResponse(
            role_id=assignment.role_principal_id,
            role_key=assignment.role_key,
            name=assignment.name,
            description=assignment.description,
            assigned_at=assignment.assigned_at,
            assigned_by_principal_id=assignment.assigned_by_principal_id,
        )
        for assignment in assignments
    ]


@router.post(
    "/{user_id}/roles",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def assign_user_role(
    user_id: UUID,
    payload: AssignRoleRequest,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_ROLES_MANAGE)),
    ],
    service: Annotated[
        RoleAssignmentService,
        Depends(get_role_assignment_service),
    ],
) -> Response:
    await service.assign_role(
        user_principal_id=user_id,
        role_principal_id=payload.role_id,
        actor_principal_id=actor_principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{user_id}/roles/{role_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_user_role(
    user_id: UUID,
    role_id: UUID,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_ROLES_MANAGE)),
    ],
    service: Annotated[
        RoleAssignmentService,
        Depends(get_role_assignment_service),
    ],
) -> Response:
    await service.revoke_role(
        user_principal_id=user_id,
        role_principal_id=role_id,
        actor_principal_id=actor_principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
