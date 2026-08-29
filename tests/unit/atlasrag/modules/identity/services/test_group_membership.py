from collections.abc import Iterable
from datetime import datetime, timezone
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.identity import (
    GroupMembershipUnitOfWork,
    IdentityRepository,
)
from atlasrag.contracts.identity_types import PrincipalState
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.helpers.errors import (
    GroupMemberTypeNotAllowed,
    GroupMembershipAlreadyExists,
    GroupCycleDetected,
    GroupPrincipalRequired,
    GroupSelfMembership,
    InvalidPrincipalType,
    PrincipalInactive,
    PrincipalNotFound,
    PrincipalRetired,
)
from atlasrag.modules.identity.services.group_membership import GroupMembershipService


class FakePrincipalRepository:
    def __init__(self, states: Iterable[PrincipalState]) -> None:
        self._states = {state.principal_id: state for state in states}
        self.find_calls: list[UUID] = []

    async def find_by_id(self, principal_id: UUID) -> PrincipalState | None:
        self.find_calls.append(principal_id)
        return self._states.get(principal_id)


class FakeMembershipRepository:
    def __init__(
        self,
        *,
        has_active_membership: bool = False,
        would_create_cycle: bool = False,
        add_error: BaseException | None = None,
    ) -> None:
        self._has_active_membership = has_active_membership
        self._would_create_cycle = would_create_cycle
        self._add_error = add_error
        self.duplicate_checks: list[tuple[UUID, UUID]] = []
        self.cycle_checks: list[tuple[UUID, UUID]] = []
        self.add_calls: list[dict[str, object]] = []

    async def has_active_membership(
        self,
        *,
        group_principal_id: UUID,
        member_principal_id: UUID,
    ) -> bool:
        self.duplicate_checks.append((group_principal_id, member_principal_id))
        return self._has_active_membership

    async def would_create_cycle(
        self,
        *,
        group_principal_id: UUID,
        member_group_principal_id: UUID,
    ) -> bool:
        self.cycle_checks.append((group_principal_id, member_group_principal_id))
        return self._would_create_cycle

    async def add_membership(
        self,
        *,
        group_principal_id: UUID,
        member_principal_id: UUID,
        member_type: str,
        added_by_principal_id: UUID,
        added_at: datetime,
    ) -> None:
        if self._add_error is not None:
            raise self._add_error
        self.add_calls.append(
            {
                "group_principal_id": group_principal_id,
                "member_principal_id": member_principal_id,
                "member_type": member_type,
                "added_by_principal_id": added_by_principal_id,
                "added_at": added_at,
            }
        )


class FakeUnitOfWork:
    def __init__(
        self,
        principals: FakePrincipalRepository,
        memberships: FakeMembershipRepository,
    ) -> None:
        self.identities = cast(IdentityRepository, object())
        self.principals = principals
        self.memberships = memberships
        self.committed = False
        self.entered = False
        self.exited = False
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

    async def commit(self) -> None:
        self.committed = True


def make_state(
    principal_id: UUID,
    principal_type: str | None,
    *,
    is_active: bool = True,
    deleted_at: datetime | None = None,
) -> PrincipalState:
    return PrincipalState(
        principal_id=principal_id,
        is_active=is_active,
        deleted_at=deleted_at,
        type=principal_type,
    )


def make_service(
    states: Iterable[PrincipalState],
    *,
    has_active_membership: bool = False,
    would_create_cycle: bool = False,
    add_error: BaseException | None = None,
) -> tuple[
    GroupMembershipService,
    FakePrincipalRepository,
    FakeMembershipRepository,
    FakeUnitOfWork,
]:
    principals = FakePrincipalRepository(states)
    memberships = FakeMembershipRepository(
        has_active_membership=has_active_membership,
        would_create_cycle=would_create_cycle,
        add_error=add_error,
    )
    uow = FakeUnitOfWork(principals, memberships)
    service = GroupMembershipService(
        lambda: cast(GroupMembershipUnitOfWork, uow),
    )
    return service, principals, memberships, uow


@pytest.mark.asyncio
async def test_add_group_member_adds_membership_and_commits() -> None:
    group_id = uuid4()
    member_id = uuid4()
    actor_id = uuid4()
    added_at = datetime(2026, 8, 30, tzinfo=timezone.utc)
    service, principals, memberships, uow = make_service(
        [
            make_state(group_id, PrincipalType.GROUP),
            make_state(member_id, PrincipalType.USER),
        ]
    )

    await service.add_group_member(
        group_id,
        member_id,
        actor_id,
        added_at,
    )

    assert principals.find_calls == [group_id, member_id]
    assert memberships.duplicate_checks == [(group_id, member_id)]
    assert memberships.cycle_checks == []
    assert memberships.add_calls == [
        {
            "group_principal_id": group_id,
            "member_principal_id": member_id,
            "member_type": PrincipalType.USER.value,
            "added_by_principal_id": actor_id,
            "added_at": added_at,
        }
    ]
    assert uow.committed is True
    assert uow.entered is True
    assert uow.exited is True
    assert uow.exit_exception_type is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("states", "expected_error"),
    [
        ([], PrincipalNotFound),
        (
            [make_state(uuid4(), PrincipalType.GROUP, is_active=False)],
            PrincipalInactive,
        ),
        (
            [
                make_state(
                    uuid4(),
                    PrincipalType.GROUP,
                    is_active=False,
                    deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            ],
            PrincipalRetired,
        ),
        ([make_state(uuid4(), PrincipalType.USER)], GroupPrincipalRequired),
    ],
)
async def test_add_group_member_validates_target_group(
    states: list[PrincipalState],
    expected_error: type[BaseException],
) -> None:
    group_id = states[0].principal_id if states else uuid4()
    member_id = uuid4()
    service, principals, memberships, uow = make_service(states)

    with pytest.raises(expected_error):
        await service.add_group_member(
            group_id,
            member_id,
            uuid4(),
            datetime.now(timezone.utc),
        )

    assert principals.find_calls == [group_id]
    assert memberships.duplicate_checks == []
    assert memberships.cycle_checks == []
    assert memberships.add_calls == []
    assert uow.committed is False
    assert uow.exit_exception_type is expected_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "member_state, expected_error",
    [
        (None, PrincipalNotFound),
        (make_state(uuid4(), PrincipalType.USER, is_active=False), PrincipalInactive),
        (
            make_state(
                uuid4(),
                PrincipalType.USER,
                is_active=False,
                deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            PrincipalRetired,
        ),
        (make_state(uuid4(), PrincipalType.ROLE), GroupMemberTypeNotAllowed),
        (make_state(uuid4(), "usr"), InvalidPrincipalType),
    ],
)
async def test_add_group_member_validates_member(
    member_state: PrincipalState | None,
    expected_error: type[BaseException],
) -> None:
    group_id = uuid4()
    member_id = member_state.principal_id if member_state is not None else uuid4()
    service, principals, memberships, uow = make_service(
        [make_state(group_id, PrincipalType.GROUP)]
        + ([member_state] if member_state is not None else [])
    )

    with pytest.raises(expected_error):
        await service.add_group_member(
            group_id,
            member_id,
            uuid4(),
            datetime.now(timezone.utc),
        )

    assert principals.find_calls == [group_id, member_id]
    assert memberships.duplicate_checks == []
    assert memberships.cycle_checks == []
    assert memberships.add_calls == []
    assert uow.committed is False
    assert uow.exit_exception_type is expected_error


@pytest.mark.asyncio
async def test_add_group_member_rejects_self_membership() -> None:
    group_id = uuid4()
    service, principals, memberships, uow = make_service(
        [make_state(group_id, PrincipalType.GROUP)]
    )

    with pytest.raises(GroupSelfMembership) as error:
        await service.add_group_member(
            group_id,
            group_id,
            uuid4(),
            datetime.now(timezone.utc),
        )

    assert principals.find_calls == []
    assert memberships.duplicate_checks == []
    assert memberships.cycle_checks == []
    assert uow.committed is False
    assert error.value.group_id == group_id
    assert error.value.member_id == group_id
    assert uow.entered is False
    assert uow.exited is False


@pytest.mark.asyncio
async def test_add_group_member_rejects_duplicate_active_membership() -> None:
    group_id = uuid4()
    member_id = uuid4()
    service, principals, memberships, uow = make_service(
        [
            make_state(group_id, PrincipalType.GROUP),
            make_state(member_id, PrincipalType.USER),
        ],
        has_active_membership=True,
    )

    with pytest.raises(GroupMembershipAlreadyExists) as error:
        await service.add_group_member(
            group_id,
            member_id,
            uuid4(),
            datetime.now(timezone.utc),
        )

    assert principals.find_calls == [group_id, member_id]
    assert memberships.duplicate_checks == [(group_id, member_id)]
    assert memberships.add_calls == []
    assert uow.committed is False
    assert uow.exit_exception_type is GroupMembershipAlreadyExists
    assert error.value.group_id == group_id
    assert error.value.member_id == member_id


@pytest.mark.asyncio
async def test_add_group_member_rejects_group_cycle() -> None:
    group_id = uuid4()
    member_group_id = uuid4()
    service, principals, memberships, uow = make_service(
        [
            make_state(group_id, PrincipalType.GROUP),
            make_state(member_group_id, PrincipalType.GROUP),
        ],
        would_create_cycle=True,
    )

    with pytest.raises(GroupCycleDetected) as error:
        await service.add_group_member(
            group_id,
            member_group_id,
            uuid4(),
            datetime.now(timezone.utc),
        )

    assert principals.find_calls == [group_id, member_group_id]
    assert memberships.duplicate_checks == [(group_id, member_group_id)]
    assert memberships.cycle_checks == [(group_id, member_group_id)]
    assert memberships.add_calls == []
    assert uow.committed is False
    assert uow.exit_exception_type is GroupCycleDetected
    assert error.value.group_id == group_id
    assert error.value.member_id == member_group_id


@pytest.mark.asyncio
async def test_add_group_member_propagates_repository_error_without_commit() -> None:
    repository_error = RuntimeError("membership insert failed")
    group_id = uuid4()
    member_id = uuid4()
    service, principals, memberships, uow = make_service(
        [
            make_state(group_id, PrincipalType.GROUP),
            make_state(member_id, PrincipalType.USER),
        ],
        add_error=repository_error,
    )

    with pytest.raises(RuntimeError, match="membership insert failed"):
        await service.add_group_member(
            group_id,
            member_id,
            uuid4(),
            datetime.now(timezone.utc),
        )

    assert principals.find_calls == [group_id, member_id]
    assert memberships.duplicate_checks == [(group_id, member_id)]
    assert memberships.cycle_checks == []
    assert uow.committed is False
    assert uow.exit_exception_type is RuntimeError
