from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from apps.api.dependencies.identity import get_principal_lifecycle
from apps.api.dependencies.permissions import require_permission
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.services.principal_lifecycle import PrincipalLifecycle

router = APIRouter(prefix="/iam/principals", tags=["principals"])


@router.patch(
    "/{principal_id}/activate",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def activate_principal(
    principal_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_PRINCIPALS_MANAGE)),
    ],
    lifecycle: Annotated[PrincipalLifecycle, Depends(get_principal_lifecycle)],
) -> Response:
    await lifecycle.activate_principal(principal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{principal_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_principal(
    principal_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_PRINCIPALS_MANAGE)),
    ],
    lifecycle: Annotated[PrincipalLifecycle, Depends(get_principal_lifecycle)],
) -> Response:
    await lifecycle.deactivate_principal(principal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{principal_id}/retire",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def retire_principal(
    principal_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_PRINCIPALS_MANAGE)),
    ],
    lifecycle: Annotated[PrincipalLifecycle, Depends(get_principal_lifecycle)],
) -> Response:
    await lifecycle.retire_principal(principal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
