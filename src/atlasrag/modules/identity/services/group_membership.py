from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from atlasrag.contracts.identity import GroupMembershipUnitOfWork
from atlasrag.contracts.types.identity import DirectGroupMember, PrincipalState
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.helpers.errors import (
    GroupCycleDetected,
    GroupMemberTypeNotAllowed,
    GroupMembershipAlreadyExists,
    GroupMembershipNotFound,
    GroupPrincipalRequired,
    GroupSelfMembership,
    InvalidPrincipalType,
    PrincipalInactive,
    PrincipalNotFound,
    PrincipalRetired,
)


class GroupMembershipService:
    def __init__(
        self,
        uow_factory: Callable[[], GroupMembershipUnitOfWork],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_group_members(
        self,
        *,
        group_id: UUID,
    ) -> tuple[DirectGroupMember, ...]:
        async with self._uow_factory() as uow:
            group = await self._get_principal(uow, group_id, role="group")
            self._ensure_group(group)
            return await uow.memberships.list_active_members(
                group_principal_id=group_id,
            )

    async def add_group_member(
        self,
        group_id: UUID,
        member_id: UUID,
        actor_id: UUID,
        added_at: datetime | None = None,
    ) -> None:
        if group_id == member_id:
            raise GroupSelfMembership(group_id=group_id, member_id=member_id)

        async with self._uow_factory() as uow:
            group = await self._get_principal(uow, group_id, role="group")
            self._ensure_active(group, role="group")
            self._ensure_group(group)

            member = await self._get_principal(uow, member_id, role="member")
            self._ensure_active(member, role="member")
            member_type = self._get_allowed_member_type(member)

            if await uow.memberships.has_active_membership(
                group_principal_id=group_id,
                member_principal_id=member_id,
            ):
                raise GroupMembershipAlreadyExists(group_id=group_id, member_id=member_id)

            if member_type == PrincipalType.GROUP and await uow.memberships.would_create_cycle(
                group_principal_id=group_id,
                member_group_principal_id=member_id,
            ):
                raise GroupCycleDetected(group_id=group_id, member_id=member_id)

            await uow.memberships.add_membership(
                group_principal_id=group_id,
                member_principal_id=member_id,
                member_type=member_type.value,
                added_by_principal_id=actor_id,
                added_at=added_at or self._clock(),
            )
            await uow.commit()

    async def remove_group_member(
        self,
        *,
        group_id: UUID,
        member_id: UUID,
        actor_id: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            group = await self._get_principal(uow, group_id, role="group")
            self._ensure_group(group)

            member = await self._get_principal(uow, member_id, role="member")
            self._get_allowed_member_type(member)

            removed = await uow.memberships.close_active_membership(
                group_principal_id=group_id,
                member_principal_id=member_id,
                removed_by_principal_id=actor_id,
                removed_at=self._clock(),
            )
            if not removed:
                raise GroupMembershipNotFound(group_id=group_id, member_id=member_id)

            await uow.commit()

    @staticmethod
    async def _get_principal(
        uow: GroupMembershipUnitOfWork,
        principal_id: UUID,
        *,
        role: str,
    ) -> PrincipalState:
        principal = await uow.principals.find_by_id(principal_id)
        if principal is None:
            raise PrincipalNotFound(principal_id=principal_id, role=role)
        return principal

    @staticmethod
    def _ensure_active(principal: PrincipalState, *, role: str) -> None:
        if principal.deleted_at is not None:
            raise PrincipalRetired(principal_id=principal.principal_id, role=role)
        if not principal.is_active:
            raise PrincipalInactive(principal_id=principal.principal_id, role=role)

    @staticmethod
    def _ensure_group(principal: PrincipalState) -> None:
        if principal.type != PrincipalType.GROUP:
            raise GroupPrincipalRequired(principal_id=principal.principal_id)

    @staticmethod
    def _get_allowed_member_type(principal: PrincipalState) -> PrincipalType:
        try:
            member_type = PrincipalType(principal.type)
        except (TypeError, ValueError) as error:
            raise InvalidPrincipalType(
                principal_id=principal.principal_id,
                principal_type=principal.type,
            ) from error

        if member_type not in (PrincipalType.USER, PrincipalType.GROUP):
            raise GroupMemberTypeNotAllowed(
                principal_id=principal.principal_id,
                principal_type=principal.type,
            )
        return member_type
