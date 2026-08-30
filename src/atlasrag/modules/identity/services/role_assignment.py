from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from atlasrag.contracts.identity import RoleAssignmentUnitOfWork
from atlasrag.contracts.identity_types import AssignedRole
from atlasrag.modules.identity.helpers.errors import (
    RoleAssignmentConflict,
    RoleAssignmentNotFound,
    RoleAssignmentRoleNotFound,
    RoleAssignmentUserNotFound,
)
from atlasrag.modules.identity.services.superadmin_policy import SuperadminPolicy


class RoleAssignmentService:
    def __init__(
        self,
        uow_factory: Callable[[], RoleAssignmentUnitOfWork],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_roles(
        self,
        *,
        user_principal_id: UUID,
    ) -> tuple[AssignedRole, ...]:
        async with self._uow_factory() as uow:
            await self._ensure_user_exists(
                uow,
                user_principal_id=user_principal_id,
            )
            return await uow.role_assignments.list_active_for_user(
                user_principal_id,
            )

    async def assign_role(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
        actor_principal_id: UUID,
    ) -> None:
        try:
            async with self._uow_factory() as uow:
                await self._ensure_targets_exist(
                    uow,
                    user_principal_id=user_principal_id,
                    role_principal_id=role_principal_id,
                )
                if await uow.role_assignments.has_active_assignment(
                    user_principal_id=user_principal_id,
                    role_principal_id=role_principal_id,
                ):
                    raise RoleAssignmentConflict(
                        user_principal_id=user_principal_id,
                        role_principal_id=role_principal_id,
                    )

                await uow.role_assignments.add_assignment(
                    user_principal_id=user_principal_id,
                    role_principal_id=role_principal_id,
                    assigned_by_principal_id=actor_principal_id,
                    assigned_at=self._clock(),
                )
                await uow.commit()
        except IntegrityError as error:
            raise RoleAssignmentConflict(
                user_principal_id=user_principal_id,
                role_principal_id=role_principal_id,
            ) from error

    async def revoke_role(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
        actor_principal_id: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            await self._ensure_targets_exist(
                uow,
                user_principal_id=user_principal_id,
                role_principal_id=role_principal_id,
            )
            if not await uow.role_assignments.has_active_assignment(
                user_principal_id=user_principal_id,
                role_principal_id=role_principal_id,
            ):
                raise RoleAssignmentNotFound(
                    user_principal_id=user_principal_id,
                    role_principal_id=role_principal_id,
                )

            policy = SuperadminPolicy(uow.superadmins)
            if await policy.is_superadmin_role(role_principal_id):
                await policy.protect_user_removal(
                    user_principal_id,
                    operation="revoke superadmin role",
                )

            revoked = await uow.role_assignments.close_active_assignment(
                user_principal_id=user_principal_id,
                role_principal_id=role_principal_id,
                revoked_by_principal_id=actor_principal_id,
                revoked_at=self._clock(),
            )
            if not revoked:
                raise RoleAssignmentNotFound(
                    user_principal_id=user_principal_id,
                    role_principal_id=role_principal_id,
                )

            await uow.commit()

    @staticmethod
    async def _ensure_targets_exist(
        uow: RoleAssignmentUnitOfWork,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
    ) -> None:
        await RoleAssignmentService._ensure_user_exists(
            uow,
            user_principal_id=user_principal_id,
        )
        if not await uow.role_assignments.role_exists(role_principal_id):
            raise RoleAssignmentRoleNotFound(role_principal_id=role_principal_id)

    @staticmethod
    async def _ensure_user_exists(
        uow: RoleAssignmentUnitOfWork,
        *,
        user_principal_id: UUID,
    ) -> None:
        if not await uow.role_assignments.user_exists(user_principal_id):
            raise RoleAssignmentUserNotFound(user_principal_id=user_principal_id)
