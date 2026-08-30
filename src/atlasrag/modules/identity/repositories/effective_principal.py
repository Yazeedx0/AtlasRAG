import uuid

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import GroupMembership, Principal, UserRole, Users


class EffectivePrincipalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_effective_principal_ids(
        self,
        user_principal_id: uuid.UUID,
    ) -> frozenset[uuid.UUID]:
        active_user = (
            select(Principal.id.label("principal_id"))
            .select_from(Principal)
            .join(Users, Users.principal_id == Principal.id)
            .where(
                Principal.id == user_principal_id,
                Principal.type == PrincipalType.USER,
                Principal.is_active.is_(True),
                Principal.deleted_at.is_(None),
            )
            .cte("active_user")
        )

        active_roles = (
            select(UserRole.role_principal_id.label("principal_id"))
            .select_from(UserRole)
            .join(
                active_user,
                active_user.c.principal_id == UserRole.user_principal_id,
            )
            .join(Principal, Principal.id == UserRole.role_principal_id)
            .where(
                UserRole.revoked_at.is_(None),
                Principal.type == PrincipalType.ROLE,
                Principal.is_active.is_(True),
                Principal.deleted_at.is_(None),
            )
        )

        effective_groups = (
            select(GroupMembership.group_principal_id.label("principal_id"))
            .select_from(GroupMembership)
            .join(
                active_user,
                active_user.c.principal_id == GroupMembership.member_principal_id,
            )
            .join(Principal, Principal.id == GroupMembership.group_principal_id)
            .where(
                GroupMembership.member_type == PrincipalType.USER,
                GroupMembership.removed_at.is_(None),
                Principal.type == PrincipalType.GROUP,
                Principal.is_active.is_(True),
                Principal.deleted_at.is_(None),
            )
            .cte("effective_groups", recursive=True)
        )
        parent_groups = (
            select(GroupMembership.group_principal_id.label("principal_id"))
            .select_from(GroupMembership)
            .join(
                effective_groups,
                effective_groups.c.principal_id == GroupMembership.member_principal_id,
            )
            .join(Principal, Principal.id == GroupMembership.group_principal_id)
            .where(
                GroupMembership.member_type == PrincipalType.GROUP,
                GroupMembership.removed_at.is_(None),
                Principal.type == PrincipalType.GROUP,
                Principal.is_active.is_(True),
                Principal.deleted_at.is_(None),
            )
        )
        effective_groups = effective_groups.union(parent_groups)

        statement = union(
            select(active_user.c.principal_id),
            active_roles,
            select(effective_groups.c.principal_id),
        )
        principal_ids = (await self._session.scalars(statement)).all()
        return frozenset(principal_ids)
