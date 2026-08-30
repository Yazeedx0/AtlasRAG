import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from atlasrag.contracts.identity_types import PrincipalState
from atlasrag.modules.identity.models import Principal


class SqlAlchemyPrincipalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(self, principal_id: uuid.UUID) -> PrincipalState | None:
        statement = select(
            Principal.id,
            Principal.type,
            Principal.is_active,
            Principal.deleted_at,
        ).where(Principal.id == principal_id).with_for_update()

        row = (await self._session.execute(statement)).one_or_none()

        if row is None:
            return None

        return PrincipalState(
            principal_id=row.id,
            is_active=row.is_active,
            deleted_at=row.deleted_at,
            type=row.type,
        )

    async def activate(self, principal_id: uuid.UUID) -> None:
        await self._update_status(
            principal_id=principal_id,
            is_active=True,
            deleted_at=None,
        )

    async def deactivate(self, principal_id: uuid.UUID) -> None:
        await self._update_status(
            principal_id=principal_id,
            is_active=False,
            deleted_at=None,
        )

    async def retire(self, principal_id: uuid.UUID) -> None:
        await self._update_status(
            principal_id=principal_id,
            is_active=False,
            deleted_at=func.now(),
        )

    async def _update_status(
        self,
        *,
        principal_id: uuid.UUID,
        is_active: bool,
        deleted_at: datetime | None | ClauseElement,
    ) -> None:
        statement = (
            update(Principal)
            .where(Principal.id == principal_id)
            .values(
                is_active=is_active,
                deleted_at=deleted_at,
                status_changed_at=func.now(),
            )
        )
        await self._session.execute(statement)
