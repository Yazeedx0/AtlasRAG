import uuid
from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.error.identity_errors import GroupMembershipAlreadyExists
from atlasrag.contracts.types.identity_types import DirectGroupMember
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import GroupMembership
from atlasrag.platform.database.integrity import is_integrity_error_for_constraint

_ACTIVE_MEMBERSHIP_CONSTRAINT = "uq_group_memberships_active_membership"


class GroupMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active_members(
        self,
        *,
        group_principal_id: uuid.UUID,
    ) -> tuple[DirectGroupMember, ...]:
        statement = (
            select(
                GroupMembership.id,
                GroupMembership.member_principal_id,
                GroupMembership.member_type,
                GroupMembership.added_at,
                GroupMembership.added_by_principal_id,
            )
            .where(
                GroupMembership.group_principal_id == group_principal_id,
                GroupMembership.removed_at.is_(None),
            )
            .order_by(GroupMembership.added_at, GroupMembership.id)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(
            DirectGroupMember(
                membership_id=row.id,
                member_principal_id=row.member_principal_id,
                member_type=row.member_type.value,
                added_at=row.added_at,
                added_by_principal_id=row.added_by_principal_id,
            )
            for row in rows
        )

    async def has_active_membership(
        self,
        *,
        group_principal_id: uuid.UUID,
        member_principal_id: uuid.UUID,
    ) -> bool:
        statement = select(
            exists().where(
                GroupMembership.group_principal_id == group_principal_id,
                GroupMembership.member_principal_id == member_principal_id,
                GroupMembership.removed_at.is_(None),
            ),
        )
        return bool(await self._session.scalar(statement))

    async def would_create_cycle(
        self,
        *,
        group_principal_id: uuid.UUID,
        member_group_principal_id: uuid.UUID,
    ) -> bool:
        reachable_groups = (
            select(GroupMembership.member_principal_id.label("group_id"))
            .where(
                GroupMembership.group_principal_id == member_group_principal_id,
                GroupMembership.member_type == PrincipalType.GROUP,
                GroupMembership.removed_at.is_(None),
            )
            .cte("reachable_groups", recursive=True)
        )
        recursive_step = select(GroupMembership.member_principal_id).where(
            GroupMembership.group_principal_id == reachable_groups.c.group_id,
            GroupMembership.member_type == PrincipalType.GROUP,
            GroupMembership.removed_at.is_(None),
        )
        reachable_groups = reachable_groups.union(recursive_step)

        statement = select(
            exists().where(reachable_groups.c.group_id == group_principal_id),
        )
        return bool(await self._session.scalar(statement))

    async def add_membership(
        self,
        *,
        group_principal_id: uuid.UUID,
        member_principal_id: uuid.UUID,
        member_type: str,
        added_by_principal_id: uuid.UUID,
        added_at: datetime,
    ) -> None:
        statement = GroupMembership.__table__.insert().values(
            id=uuid.uuid4(),
            group_principal_id=group_principal_id,
            member_principal_id=member_principal_id,
            member_type=PrincipalType(member_type),
            added_at=added_at,
            added_by_principal_id=added_by_principal_id,
            removed_at=None,
            removed_by_principal_id=None,
        )

        try:
            await self._session.execute(statement)
        except IntegrityError as error:
            if not is_integrity_error_for_constraint(
                error=error,
                constraint_name=_ACTIVE_MEMBERSHIP_CONSTRAINT,
            ):
                raise
            raise GroupMembershipAlreadyExists(
                group_id=group_principal_id,
                member_id=member_principal_id,
            ) from error

    async def close_active_membership(
        self,
        *,
        group_principal_id: uuid.UUID,
        member_principal_id: uuid.UUID,
        removed_by_principal_id: uuid.UUID,
        removed_at: datetime,
    ) -> bool:
        statement = (
            update(GroupMembership)
            .where(
                GroupMembership.group_principal_id == group_principal_id,
                GroupMembership.member_principal_id == member_principal_id,
                GroupMembership.removed_at.is_(None),
            )
            .values(
                removed_at=removed_at,
                removed_by_principal_id=removed_by_principal_id,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount > 0
