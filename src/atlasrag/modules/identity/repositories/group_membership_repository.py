import uuid
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.identity_errors import GroupMembershipAlreadyExists
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import GroupMembership

_ACTIVE_MEMBERSHIP_CONSTRAINT = "uq_group_memberships_active_membership"


def _is_active_membership_conflict(error: IntegrityError) -> bool:
    orig = error.orig
    constraint_name = getattr(orig, "constraint_name", None)
    if constraint_name is None:
        diagnostic = getattr(orig, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)

    if constraint_name is not None:
        return constraint_name == _ACTIVE_MEMBERSHIP_CONSTRAINT

    return _ACTIVE_MEMBERSHIP_CONSTRAINT in str(orig)


class SqlAlchemyGroupMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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

    async def has_group_path(
        self,
        *,
        start_group_id: uuid.UUID,
        target_group_id: uuid.UUID,
    ) -> bool:
        reachable_groups = (
            select(GroupMembership.member_principal_id.label("group_id"))
            .where(
                GroupMembership.group_principal_id == start_group_id,
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
            exists().where(reachable_groups.c.group_id == target_group_id),
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
            if not _is_active_membership_conflict(error):
                raise
            raise GroupMembershipAlreadyExists(
                group_id=group_principal_id,
                member_id=member_principal_id,
            ) from error
