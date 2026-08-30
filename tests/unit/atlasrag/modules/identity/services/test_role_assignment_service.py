from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.error.identity_errors import RoleAssignmentNotFound
from atlasrag.contracts.error.permission_errors import LastSuperadminViolation
from atlasrag.modules.identity.services.role_assignment import RoleAssignmentService

_NOW = datetime(2026, 8, 30, tzinfo=UTC)


class FakeRoleAssignmentRepository:
    def __init__(self, *, active: bool = True, close_result: bool = True) -> None:
        self.active = active
        self.close_result = close_result
        self.close_calls: list[tuple[UUID, UUID, UUID, datetime]] = []

    async def user_exists(self, user_principal_id: UUID) -> bool:
        return True

    async def role_exists(self, role_principal_id: UUID) -> bool:
        return True

    async def has_active_assignment(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
    ) -> bool:
        return self.active

    async def close_active_assignment(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
        revoked_by_principal_id: UUID,
        revoked_at: datetime,
    ) -> bool:
        self.close_calls.append(
            (
                user_principal_id,
                role_principal_id,
                revoked_by_principal_id,
                revoked_at,
            )
        )
        return self.close_result


class FakeSuperadminRepository:
    def __init__(self, *, role_id: UUID, user_id: UUID, active_count: int) -> None:
        self.role_id = role_id
        self.user_id = user_id
        self.active_count = active_count
        self.lock_calls = 0

    async def find_superadmin_role_id(self) -> UUID | None:
        return self.role_id

    async def lock_superadmin_role(self) -> UUID | None:
        self.lock_calls += 1
        return self.role_id

    async def user_has_superadmin_role(self, user_principal_id: UUID) -> bool:
        return user_principal_id == self.user_id

    async def count_active_superadmins(self, role_principal_id: UUID) -> int:
        return self.active_count


class FakeUnitOfWork:
    def __init__(
        self,
        role_assignments: FakeRoleAssignmentRepository,
        superadmins: FakeSuperadminRepository,
    ) -> None:
        self.role_assignments = role_assignments
        self.superadmins = superadmins
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.rolled_back = exc_type is not None

    async def commit(self) -> None:
        self.committed = True


def make_service(
    *,
    active_count: int,
    assignment_active: bool = True,
) -> tuple[
    RoleAssignmentService,
    FakeUnitOfWork,
    FakeRoleAssignmentRepository,
    UUID,
    UUID,
]:
    role_id = uuid4()
    user_id = uuid4()
    assignments = FakeRoleAssignmentRepository(active=assignment_active)
    superadmins = FakeSuperadminRepository(
        role_id=role_id,
        user_id=user_id,
        active_count=active_count,
    )
    uow = FakeUnitOfWork(assignments, superadmins)
    service = RoleAssignmentService(
        lambda: uow,  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )
    return service, uow, assignments, user_id, role_id


@pytest.mark.asyncio
async def test_revoke_role_allows_one_of_two_active_superadmins() -> None:
    service, uow, assignments, user_id, role_id = make_service(active_count=2)
    actor_id = uuid4()

    await service.revoke_role(
        user_principal_id=user_id,
        role_principal_id=role_id,
        actor_principal_id=actor_id,
    )

    assert assignments.close_calls == [(user_id, role_id, actor_id, _NOW)]
    assert uow.committed is True


@pytest.mark.asyncio
async def test_revoke_role_rejects_last_active_superadmin() -> None:
    service, uow, assignments, user_id, role_id = make_service(active_count=1)

    with pytest.raises(LastSuperadminViolation):
        await service.revoke_role(
            user_principal_id=user_id,
            role_principal_id=role_id,
            actor_principal_id=uuid4(),
        )

    assert assignments.close_calls == []
    assert uow.committed is False
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_revoke_role_rejects_missing_active_assignment_before_policy() -> None:
    service, uow, assignments, user_id, role_id = make_service(
        active_count=1,
        assignment_active=False,
    )

    with pytest.raises(RoleAssignmentNotFound):
        await service.revoke_role(
            user_principal_id=user_id,
            role_principal_id=role_id,
            actor_principal_id=uuid4(),
        )

    assert assignments.close_calls == []
    assert uow.rolled_back is True
