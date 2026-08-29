from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from atlasrag.contracts.identity import GroupMembershipUnitOfWork, PrincipalState
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.helpers.errors import (
    GroupMemberTypeNotAllowed,
    GroupMembershipAlreadyExists,
    GroupMembershipCycle,
    GroupPrincipalRequired,
    GroupSelfMembership,
    PrincipalInactive,
    PrincipalNotFound,
    PrincipalRetired,
)


class GroupMembershipService:
    def __init__(self, uow_factory: Callable[[], GroupMembershipUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def add_group_member(
        self,
        group_id: UUID,
        member_id: UUID,
        actor_id: UUID,
        added_at: datetime,
    ) -> None:
        async with self._uow_factory() as uow:
            group = await self._get_principal(uow, group_id)
            self._ensure_active(group)
            self._ensure_group(group)

            member = await self._get_principal(uow, member_id)
            self._ensure_active(member)
            member_type = self._get_allowed_member_type(member)

            if group_id == member_id:
                raise GroupSelfMembership

            if await uow.memberships.has_active_membership(
                group_principal_id=group_id,
                member_principal_id=member_id,
            ):
                raise GroupMembershipAlreadyExists

            if member_type == PrincipalType.GROUP and await uow.memberships.has_group_path(
                start_group_id=member_id,
                target_group_id=group_id,
            ):
                raise GroupMembershipCycle

            await uow.memberships.add_membership(
                group_principal_id=group_id,
                member_principal_id=member_id,
                member_type=member_type.value,
                added_by_principal_id=actor_id,
                added_at=added_at,
            )
            await uow.commit()

    @staticmethod
    async def _get_principal(
        uow: GroupMembershipUnitOfWork,
        principal_id: UUID,
    ) -> PrincipalState:
        principal = await uow.principals.find_by_id(principal_id)
        if principal is None:
            raise PrincipalNotFound
        return principal

    @staticmethod
    def _ensure_active(principal: PrincipalState) -> None:
        if principal.deleted_at is not None:
            raise PrincipalRetired
        if not principal.is_active:
            raise PrincipalInactive

    @staticmethod
    def _ensure_group(principal: PrincipalState) -> None:
        if principal.type != PrincipalType.GROUP:
            raise GroupPrincipalRequired

    @staticmethod
    def _get_allowed_member_type(principal: PrincipalState) -> PrincipalType:
        try:
            member_type = PrincipalType(principal.type)
        except (TypeError, ValueError) as error:
            raise GroupMemberTypeNotAllowed from error

        if member_type not in (PrincipalType.USER, PrincipalType.GROUP):
            raise GroupMemberTypeNotAllowed
        return member_type
