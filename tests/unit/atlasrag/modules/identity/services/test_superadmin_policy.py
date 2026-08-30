from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.error.permission_errors import (
    LastSuperadminViolation,
    ProtectedSuperadminRole,
)
from atlasrag.modules.identity.services.superadmin_policy import SuperadminPolicy


class FakeSuperadminRepository:
    def __init__(
        self,
        *,
        role_id: UUID | None,
        assigned_user_ids: frozenset[UUID] = frozenset(),
        active_count: int = 0,
    ) -> None:
        self.role_id = role_id
        self.assigned_user_ids = assigned_user_ids
        self.active_count = active_count
        self.lock_calls = 0
        self.count_calls: list[UUID] = []

    async def find_superadmin_role_id(self) -> UUID | None:
        return self.role_id

    async def lock_superadmin_role(self) -> UUID | None:
        self.lock_calls += 1
        return self.role_id

    async def user_has_superadmin_role(self, user_principal_id: UUID) -> bool:
        return user_principal_id in self.assigned_user_ids

    async def count_active_superadmins(self, role_principal_id: UUID) -> int:
        self.count_calls.append(role_principal_id)
        return self.active_count


@pytest.mark.asyncio
async def test_protect_role_lifecycle_rejects_superadmin_role() -> None:
    role_id = uuid4()
    policy = SuperadminPolicy(FakeSuperadminRepository(role_id=role_id))

    with pytest.raises(ProtectedSuperadminRole):
        await policy.protect_role_lifecycle(
            role_id,
            operation="retire principal",
        )


@pytest.mark.asyncio
async def test_protect_role_lifecycle_allows_other_principal() -> None:
    policy = SuperadminPolicy(FakeSuperadminRepository(role_id=uuid4()))

    await policy.protect_role_lifecycle(
        uuid4(),
        operation="retire principal",
    )


@pytest.mark.asyncio
async def test_protect_user_removal_allows_non_superadmin() -> None:
    role_id = uuid4()
    repository = FakeSuperadminRepository(role_id=role_id, active_count=1)
    policy = SuperadminPolicy(repository)

    await policy.protect_user_removal(
        uuid4(),
        operation="deactivate principal",
    )

    assert repository.lock_calls == 1
    assert repository.count_calls == []


@pytest.mark.asyncio
async def test_protect_user_removal_allows_one_of_two_superadmins() -> None:
    role_id = uuid4()
    user_id = uuid4()
    repository = FakeSuperadminRepository(
        role_id=role_id,
        assigned_user_ids=frozenset({user_id}),
        active_count=2,
    )
    policy = SuperadminPolicy(repository)

    await policy.protect_user_removal(
        user_id,
        operation="revoke superadmin role",
    )

    assert repository.count_calls == [role_id]


@pytest.mark.asyncio
async def test_protect_user_removal_rejects_last_superadmin() -> None:
    role_id = uuid4()
    user_id = uuid4()
    repository = FakeSuperadminRepository(
        role_id=role_id,
        assigned_user_ids=frozenset({user_id}),
        active_count=1,
    )
    policy = SuperadminPolicy(repository)

    with pytest.raises(LastSuperadminViolation) as raised:
        await policy.protect_user_removal(
            user_id,
            operation="revoke superadmin role",
        )

    assert raised.value.user_principal_id == user_id
    assert repository.count_calls == [role_id]


@pytest.mark.asyncio
async def test_protect_user_removal_fails_closed_when_system_role_is_missing() -> None:
    policy = SuperadminPolicy(FakeSuperadminRepository(role_id=None))

    with pytest.raises(ProtectedSuperadminRole):
        await policy.protect_user_removal(
            uuid4(),
            operation="deactivate principal",
        )
