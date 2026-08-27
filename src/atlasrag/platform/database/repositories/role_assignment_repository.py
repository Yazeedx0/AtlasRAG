import uuid
from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.platform.database.models import Role, UserRole, Users


class SqlAlchemyRoleAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def user_exists(self, user_principal_id: uuid.UUID) -> bool:
        statement = select(
            exists().where(Users.principal_id == user_principal_id),
        )
        return bool(await self._session.scalar(statement))

    async def role_exists(self, role_principal_id: uuid.UUID) -> bool:
        statement = select(
            exists().where(Role.principal_id == role_principal_id),
        )
        return bool(await self._session.scalar(statement))

    async def has_active_assignment(
        self,
        *,
        user_principal_id: uuid.UUID,
        role_principal_id: uuid.UUID,
    ) -> bool:
        statement = select(
            exists().where(
                UserRole.user_principal_id == user_principal_id,
                UserRole.role_principal_id == role_principal_id,
                UserRole.revoked_at.is_(None),
            ),
        )
        return bool(await self._session.scalar(statement))

    async def add_assignment(
        self,
        *,
        user_principal_id: uuid.UUID,
        role_principal_id: uuid.UUID,
        assigned_by_principal_id: uuid.UUID,
        assigned_at: datetime,
    ) -> None:
        statement = UserRole.__table__.insert().values(
            id=uuid.uuid4(),
            user_principal_id=user_principal_id,
            role_principal_id=role_principal_id,
            assigned_at=assigned_at,
            assigned_by_principal_id=assigned_by_principal_id,
            revoked_at=None,
            revoked_by_principal_id=None,
        )
        await self._session.execute(statement)

    async def close_active_assignment(
        self,
        *,
        user_principal_id: uuid.UUID,
        role_principal_id: uuid.UUID,
        revoked_by_principal_id: uuid.UUID,
        revoked_at: datetime,
    ) -> bool:
        statement = (
            update(UserRole)
            .where(
                UserRole.user_principal_id == user_principal_id,
                UserRole.role_principal_id == role_principal_id,
                UserRole.revoked_at.is_(None),
            )
            .values(
                revoked_at=revoked_at,
                revoked_by_principal_id=revoked_by_principal_id,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount > 0
