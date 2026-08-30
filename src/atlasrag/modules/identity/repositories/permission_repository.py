import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.models import PermissionDefinition, PrincipalPermission


class SqlAlchemyPermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def permission_exists(self, permission: Permission) -> bool:
        statement = select(
            exists().where(
                PermissionDefinition.permission_key == permission.value,
            )
        )
        return bool(await self._session.scalar(statement))

    async def has_permission(
        self,
        *,
        principal_ids: Collection[uuid.UUID],
        permission: Permission,
        at: datetime,
    ) -> bool:
        if not principal_ids:
            return False

        statement = select(
            exists().where(
                PrincipalPermission.principal_id.in_(principal_ids),
                PrincipalPermission.permission_key == permission.value,
                PrincipalPermission.granted_at <= at,
                PrincipalPermission.revoked_at.is_(None),
            )
        )
        return bool(await self._session.scalar(statement))

    async def has_active_grant(
        self,
        *,
        principal_id: uuid.UUID,
        permission: Permission,
    ) -> bool:
        statement = select(
            exists().where(
                PrincipalPermission.principal_id == principal_id,
                PrincipalPermission.permission_key == permission.value,
                PrincipalPermission.revoked_at.is_(None),
            )
        )
        return bool(await self._session.scalar(statement))

    async def add_grant(
        self,
        *,
        principal_id: uuid.UUID,
        permission: Permission,
        granted_by_principal_id: uuid.UUID | None,
        granted_at: datetime,
    ) -> None:
        self._session.add(
            PrincipalPermission(
                principal_id=principal_id,
                permission_key=permission.value,
                granted_at=granted_at,
                granted_by_principal_id=granted_by_principal_id,
            )
        )

    async def revoke_active_grant(
        self,
        *,
        principal_id: uuid.UUID,
        permission: Permission,
        revoked_by_principal_id: uuid.UUID | None,
        revoked_at: datetime,
    ) -> bool:
        statement = (
            update(PrincipalPermission)
            .where(
                PrincipalPermission.principal_id == principal_id,
                PrincipalPermission.permission_key == permission.value,
                PrincipalPermission.revoked_at.is_(None),
            )
            .values(
                revoked_at=revoked_at,
                revoked_by_principal_id=revoked_by_principal_id,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount > 0
