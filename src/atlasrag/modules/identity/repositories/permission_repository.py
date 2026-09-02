import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types.identity import (
    ActivePermissionGrant,
    PermissionDefinitionState,
)
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.models import PermissionDefinition, PrincipalPermission


class PermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_permissions(self) -> tuple[PermissionDefinitionState, ...]:
        statement = select(
            PermissionDefinition.permission_key,
            PermissionDefinition.description,
        ).order_by(PermissionDefinition.permission_key)
        rows = (await self._session.execute(statement)).all()
        return tuple(
            PermissionDefinitionState(
                permission_key=row.permission_key,
                description=row.description,
            )
            for row in rows
        )

    async def list_active_for_principal(
        self,
        *,
        principal_id: uuid.UUID,
    ) -> tuple[ActivePermissionGrant, ...]:
        statement = (
            select(
                PrincipalPermission.permission_key,
                PermissionDefinition.description,
                PrincipalPermission.granted_at,
                PrincipalPermission.granted_by_principal_id,
            )
            .join(
                PermissionDefinition,
                PermissionDefinition.permission_key == PrincipalPermission.permission_key,
            )
            .where(
                PrincipalPermission.principal_id == principal_id,
                PrincipalPermission.revoked_at.is_(None),
            )
            .order_by(PrincipalPermission.permission_key)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(
            ActivePermissionGrant(
                permission_key=row.permission_key,
                description=row.description,
                granted_at=row.granted_at,
                granted_by_principal_id=row.granted_by_principal_id,
            )
            for row in rows
        )

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
