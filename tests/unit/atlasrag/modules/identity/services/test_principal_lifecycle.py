from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from types import TracebackType
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.identity import PrincipalState
from atlasrag.modules.identity.helpers.errors import PrincipalNotFound, PrincipalRetired
from atlasrag.modules.identity.services.principal_lifecycle import PrincipalLifecycle

LifecycleOperation = Callable[[PrincipalLifecycle, UUID], Awaitable[None]]


class FakePrincipalRepository:
    def __init__(
        self,
        state: PrincipalState | None,
        *,
        mutation_error: BaseException | None = None,
    ) -> None:
        self._state = state
        self._mutation_error = mutation_error
        self.find_calls: list[UUID] = []
        self.activate_calls: list[UUID] = []
        self.deactivate_calls: list[UUID] = []
        self.retire_calls: list[UUID] = []

    async def find_by_id(self, principal_id: UUID) -> PrincipalState | None:
        self.find_calls.append(principal_id)
        return self._state

    async def activate(self, principal_id: UUID) -> None:
        self._raise_mutation_error()
        self.activate_calls.append(principal_id)

    async def deactivate(self, principal_id: UUID) -> None:
        self._raise_mutation_error()
        self.deactivate_calls.append(principal_id)

    async def retire(self, principal_id: UUID) -> None:
        self._raise_mutation_error()
        self.retire_calls.append(principal_id)

    def _raise_mutation_error(self) -> None:
        if self._mutation_error is not None:
            raise self._mutation_error


class FakeUnitOfWork:
    def __init__(self, repository: FakePrincipalRepository) -> None:
        self.principals = repository
        self.committed = False
        self.entered = False
        self.exited = False
        self.rolled_back = False
        self.exit_exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeUnitOfWork":
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True
        self.exit_exception_type = exc_type
        self.rolled_back = exc_type is not None

    async def commit(self) -> None:
        self.committed = True


def make_lifecycle(
    state: PrincipalState | None,
    *,
    mutation_error: BaseException | None = None,
) -> tuple[PrincipalLifecycle, FakePrincipalRepository, FakeUnitOfWork]:
    repository = FakePrincipalRepository(state, mutation_error=mutation_error)
    uow = FakeUnitOfWork(repository)
    lifecycle = PrincipalLifecycle(lambda: uow)  # type: ignore[arg-type]
    return lifecycle, repository, uow


def make_state(
    principal_id: UUID,
    *,
    is_active: bool,
    deleted_at: datetime | None = None,
) -> PrincipalState:
    return PrincipalState(
        principal_id=principal_id,
        is_active=is_active,
        deleted_at=deleted_at,
    )


@pytest.mark.asyncio
async def test_activate_principal_updates_inactive_principal_and_commits() -> None:
    principal_id = uuid4()
    lifecycle, repository, uow = make_lifecycle(
        make_state(principal_id, is_active=False),
    )

    await lifecycle.activate_principal(principal_id)

    assert repository.find_calls == [principal_id]
    assert repository.activate_calls == [principal_id]
    assert repository.deactivate_calls == []
    assert repository.retire_calls == []
    assert uow.committed is True
    assert uow.entered is True
    assert uow.exited is True
    assert uow.exit_exception_type is None


@pytest.mark.asyncio
async def test_activate_principal_is_idempotent_for_active_principal() -> None:
    principal_id = uuid4()
    lifecycle, repository, uow = make_lifecycle(
        make_state(principal_id, is_active=True),
    )

    await lifecycle.activate_principal(principal_id)

    assert repository.find_calls == [principal_id]
    assert repository.activate_calls == []
    assert uow.committed is False
    assert uow.exited is True


@pytest.mark.asyncio
async def test_deactivate_principal_updates_active_principal_and_commits() -> None:
    principal_id = uuid4()
    lifecycle, repository, uow = make_lifecycle(
        make_state(principal_id, is_active=True),
    )

    await lifecycle.deactivate_principal(principal_id)

    assert repository.find_calls == [principal_id]
    assert repository.deactivate_calls == [principal_id]
    assert repository.activate_calls == []
    assert repository.retire_calls == []
    assert uow.committed is True
    assert uow.exited is True
    assert uow.exit_exception_type is None


@pytest.mark.asyncio
async def test_deactivate_principal_is_idempotent_for_inactive_principal() -> None:
    principal_id = uuid4()
    lifecycle, repository, uow = make_lifecycle(
        make_state(principal_id, is_active=False),
    )

    await lifecycle.deactivate_principal(principal_id)

    assert repository.find_calls == [principal_id]
    assert repository.deactivate_calls == []
    assert uow.committed is False
    assert uow.exited is True


@pytest.mark.asyncio
async def test_retire_principal_deactivates_and_commits() -> None:
    principal_id = uuid4()
    lifecycle, repository, uow = make_lifecycle(
        make_state(principal_id, is_active=True),
    )

    await lifecycle.retire_principal(principal_id)

    assert repository.find_calls == [principal_id]
    assert repository.retire_calls == [principal_id]
    assert repository.activate_calls == []
    assert repository.deactivate_calls == []
    assert uow.committed is True
    assert uow.exited is True
    assert uow.exit_exception_type is None


@pytest.mark.asyncio
async def test_lifecycle_propagates_repository_error_and_rolls_back() -> None:
    principal_id = uuid4()
    repository_error = RuntimeError("principal update failed")
    lifecycle, repository, uow = make_lifecycle(
        make_state(principal_id, is_active=False),
        mutation_error=repository_error,
    )

    with pytest.raises(RuntimeError, match="principal update failed"):
        await lifecycle.activate_principal(principal_id)

    assert repository.find_calls == [principal_id]
    assert repository.activate_calls == []
    assert uow.committed is False
    assert uow.rolled_back is True
    assert uow.exit_exception_type is RuntimeError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        PrincipalLifecycle.activate_principal,
        PrincipalLifecycle.deactivate_principal,
        PrincipalLifecycle.retire_principal,
    ],
)
async def test_lifecycle_raises_for_missing_principal(operation: LifecycleOperation) -> None:
    principal_id = uuid4()
    lifecycle, repository, uow = make_lifecycle(None)

    with pytest.raises(PrincipalNotFound):
        await operation(lifecycle, principal_id)

    assert repository.find_calls == [principal_id]
    assert repository.activate_calls == []
    assert repository.deactivate_calls == []
    assert repository.retire_calls == []
    assert uow.committed is False
    assert uow.rolled_back is True
    assert uow.exit_exception_type is PrincipalNotFound


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        PrincipalLifecycle.activate_principal,
        PrincipalLifecycle.deactivate_principal,
        PrincipalLifecycle.retire_principal,
    ],
)
async def test_lifecycle_rejects_retired_principal(operation: LifecycleOperation) -> None:
    principal_id = uuid4()
    lifecycle, repository, uow = make_lifecycle(
        make_state(
            principal_id,
            is_active=False,
            deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )

    with pytest.raises(PrincipalRetired):
        await operation(lifecycle, principal_id)

    assert repository.find_calls == [principal_id]
    assert repository.activate_calls == []
    assert repository.deactivate_calls == []
    assert repository.retire_calls == []
    assert uow.committed is False
    assert uow.rolled_back is True
    assert uow.exit_exception_type is PrincipalRetired
