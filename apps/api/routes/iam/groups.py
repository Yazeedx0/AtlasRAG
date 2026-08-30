from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from apps.api.dependencies.identity import get_group_membership_service
from apps.api.dependencies.permissions import require_permission
from apps.api.schemas.iam.groups import AddGroupMemberRequest, GroupMemberResponse
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.services.group_membership import GroupMembershipService

router = APIRouter(prefix="/iam/groups", tags=["groups"])


@router.get(
    "/{group_id}/members",
    response_model=list[GroupMemberResponse],
    status_code=status.HTTP_200_OK,
)
async def list_group_members(
    group_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_GROUPS_MANAGE)),
    ],
    service: Annotated[
        GroupMembershipService,
        Depends(get_group_membership_service),
    ],
) -> list[GroupMemberResponse]:
    members = await service.list_group_members(group_id=group_id)
    return [
        GroupMemberResponse(
            membership_id=member.membership_id,
            member_id=member.member_principal_id,
            member_type=member.member_type,
            added_at=member.added_at,
            added_by_principal_id=member.added_by_principal_id,
        )
        for member in members
    ]


@router.post(
    "/{group_id}/members",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def add_group_member(
    group_id: UUID,
    payload: AddGroupMemberRequest,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_GROUPS_MANAGE)),
    ],
    service: Annotated[
        GroupMembershipService,
        Depends(get_group_membership_service),
    ],
) -> Response:
    await service.add_group_member(
        group_id=group_id,
        member_id=payload.member_id,
        actor_id=actor_principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{group_id}/members/{member_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_member(
    group_id: UUID,
    member_id: UUID,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.IAM_GROUPS_MANAGE)),
    ],
    service: Annotated[
        GroupMembershipService,
        Depends(get_group_membership_service),
    ],
) -> Response:
    await service.remove_group_member(
        group_id=group_id,
        member_id=member_id,
        actor_id=actor_principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
