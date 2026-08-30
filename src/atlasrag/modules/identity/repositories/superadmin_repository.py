import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.modules.identity.builtin_roles import SUPERADMIN_ROLE_KEY
from atlasrag.modules.identity.models import Principal, Role, UserRole


class SuperadminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_superadmin_role_id(self) -> uuid.UUID | None:
        statement = select(Role.principal_id).where(
            Role.role_key == SUPERADMIN_ROLE_KEY
        )
        return await self._session.scalar(statement)

    async def lock_superadmin_role(self) -> uuid.UUID | None:
        statement = (
            select(Role.principal_id)
            .where(Role.role_key == SUPERADMIN_ROLE_KEY)
            .with_for_update()
        )
        return await self._session.scalar(statement)

    async def user_has_superadmin_role(
        self,
        user_principal_id: uuid.UUID,
    ) -> bool:
        role_id = await self.find_superadmin_role_id()
        if role_id is None:
            return False

        statement = select(
            exists(
                select(UserRole.id)
                .join(Principal, Principal.id == UserRole.user_principal_id)
                .where(
                    UserRole.user_principal_id == user_principal_id,
                    UserRole.role_principal_id == role_id,
                    UserRole.revoked_at.is_(None),
                    Principal.is_active.is_(True),
                    Principal.deleted_at.is_(None),
                )
            )
        )
        return bool(await self._session.scalar(statement))

    async def count_active_superadmins(
        self,
        role_principal_id: uuid.UUID,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(UserRole)
            .join(Principal, Principal.id == UserRole.user_principal_id)
            .where(
                UserRole.role_principal_id == role_principal_id,
                UserRole.revoked_at.is_(None),
                Principal.is_active.is_(True),
                Principal.deleted_at.is_(None),
            )
        )
        value = await self._session.scalar(statement)
        return int(value or 0)
