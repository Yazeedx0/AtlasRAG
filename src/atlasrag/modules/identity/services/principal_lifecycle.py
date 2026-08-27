from collections.abc import Callable
from uuid import UUID

from atlasrag.contracts.identity import IdentityUnitOfWork, PrincipalState
from atlasrag.modules.identity.helpers.errors import PrincipalNotFound, PrincipalRetired


class PrincipalLifecycle:
    def __init__(self, uow_factory: Callable[[], IdentityUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def activate_principal(self, principal_id: UUID) -> None:
        async with self._uow_factory() as uow:
            principal = await self._get_principal(uow, principal_id)
            self._ensure_not_retired(principal)

            if principal.is_active:
                return

            await uow.principals.activate(principal_id)
            await uow.commit()

    async def deactivate_principal(self, principal_id: UUID) -> None:
        async with self._uow_factory() as uow:
            principal = await self._get_principal(uow, principal_id)
            self._ensure_not_retired(principal)

            if not principal.is_active:
                return

            await uow.principals.deactivate(principal_id)
            await uow.commit()

    async def retire_principal(self, principal_id: UUID) -> None:
        async with self._uow_factory() as uow:
            principal = await self._get_principal(uow, principal_id)
            self._ensure_not_retired(principal)

            await uow.principals.retire(principal_id)
            await uow.commit()

    @staticmethod
    async def _get_principal(
        uow: IdentityUnitOfWork,
        principal_id: UUID,
    ) -> PrincipalState:
        principal = await uow.principals.find_by_id(principal_id)
        if principal is None:
            raise PrincipalNotFound
        return principal

    @staticmethod
    def _ensure_not_retired(principal: PrincipalState) -> None:
        if principal.deleted_at is not None:
            raise PrincipalRetired
