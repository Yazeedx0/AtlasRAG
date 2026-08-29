from datetime import datetime, timezone
from types import TracebackType
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.identity_types import LocalUserIdentity
from atlasrag.modules.identity.helpers.errors import (
    IdentityAlreadyProvisioned,
    IdentityProvisioningConflict,
    LocalIdentityDisabled,
    LocalIdentityNotProvisioned,
    LocalIdentityRetired,
)
from atlasrag.modules.identity.services.identity_resolver import IdentityResolver


class FakeIdentityRepository:
    def __init__(
        self,
        result: LocalUserIdentity | None,
    ) -> None:
        self._result = result
        self.lookup_calls: list[tuple[str, str]] = []

    async def find_by_oidc_subject(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> LocalUserIdentity | None:
        self.lookup_calls.append((issuer, subject))
        return self._result


class FakePolicy:
    def __init__(self, *, jit_enabled: bool) -> None:
        self._jit_enabled = jit_enabled

    def jit_enabled(self) -> bool:
        return self._jit_enabled


class FailingUowFactory:
    def __call__(self) -> None:
        raise AssertionError("uow_factory should not be called on this path")


class FakeProvisioningRepository:
    def __init__(
        self,
        *,
        recheck_result: LocalUserIdentity | None = None,
        provisioned_principal_id: UUID | None = None,
        conflict: bool = False,
        provision_error: BaseException | None = None,
    ) -> None:
        self._recheck_result = recheck_result
        self.provisioned_principal_id = provisioned_principal_id
        self._conflict = conflict
        self._provision_error = provision_error
        self.lookup_calls: list[tuple[str, str]] = []
        self.provision_calls: list[AuthenticatedIdentity] = []

    async def find_by_oidc_subject(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> LocalUserIdentity | None:
        self.lookup_calls.append((issuer, subject))
        return self._recheck_result

    async def provision_user(self, identity: AuthenticatedIdentity) -> UUID:
        self.provision_calls.append(identity)
        if self._provision_error is not None:
            raise self._provision_error
        if self._conflict:
            raise IdentityAlreadyProvisioned
        if self.provisioned_principal_id is None:
            raise AssertionError("provisioned principal id is required")
        return self.provisioned_principal_id


class FakeUnitOfWork:
    def __init__(
        self,
        identities: FakeProvisioningRepository,
        *,
        name: str = "uow",
        events: list[str] | None = None,
    ) -> None:
        self.identities = identities
        self.name = name
        self.events = events if events is not None else []
        self.committed = False
        self.entered = False
        self.exited = False
        self.rolled_back = False
        self.exit_exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeUnitOfWork":
        self.entered = True
        self.events.append(f"{self.name}:enter")
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
        self.events.append(f"{self.name}:exit")

    async def commit(self) -> None:
        self.committed = True
        self.events.append(f"{self.name}:commit")


class SequencedUowFactory:
    """Returns a different UOW instance on each call, mirroring how a real
    uow_factory opens a fresh session/transaction every time it's invoked."""

    def __init__(self, uows: list[FakeUnitOfWork]) -> None:
        self._uows = list(uows)
        self.calls = 0

    def __call__(self) -> FakeUnitOfWork:
        uow = self._uows[self.calls]
        self.calls += 1
        return uow


def make_identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        issuer="https://auth.example.com/realms/atlas",
        subject="user-123",
    )


@pytest.mark.asyncio
async def test_resolve_returns_active_principal_id() -> None:
    principal_id = uuid4()
    identity = make_identity()

    repository = FakeIdentityRepository(
        LocalUserIdentity(
            principal_id=principal_id,
            is_active=True,
            deleted_at=None,
        )
    )

    resolver = IdentityResolver(
        repository,
        FailingUowFactory(),
        FakePolicy(jit_enabled=False),
    )

    result = await resolver.resolve(identity)

    assert result == principal_id
    assert repository.lookup_calls == [(identity.issuer, identity.subject)]


@pytest.mark.asyncio
async def test_resolve_uses_issuer_and_subject_without_email_or_username_fallback() -> None:
    principal_id = uuid4()
    identity = AuthenticatedIdentity(
        issuer="https://auth.example.com/realms/atlas",
        subject="subject-456",
        email="different@example.com",
        username="different-user",
    )
    repository = FakeIdentityRepository(
        LocalUserIdentity(
            principal_id=principal_id,
            is_active=True,
            deleted_at=None,
        )
    )

    resolver = IdentityResolver(
        repository,
        FailingUowFactory(),
        FakePolicy(jit_enabled=False),
    )

    result = await resolver.resolve(identity)

    assert result == principal_id
    assert repository.lookup_calls == [(identity.issuer, identity.subject)]


@pytest.mark.asyncio
async def test_resolve_rejects_unknown_identity_when_jit_disabled() -> None:
    resolver = IdentityResolver(
        FakeIdentityRepository(None),
        FailingUowFactory(),
        FakePolicy(jit_enabled=False),
    )

    with pytest.raises(LocalIdentityNotProvisioned):
        await resolver.resolve(make_identity())


@pytest.mark.asyncio
async def test_resolve_rejects_disabled_principal() -> None:
    resolver = IdentityResolver(
        FakeIdentityRepository(
            LocalUserIdentity(
                principal_id=uuid4(),
                is_active=False,
                deleted_at=None,
            )
        ),
        FailingUowFactory(),
        FakePolicy(jit_enabled=False),
    )

    with pytest.raises(LocalIdentityDisabled):
        await resolver.resolve(make_identity())


@pytest.mark.asyncio
async def test_resolve_rejects_retired_principal() -> None:
    resolver = IdentityResolver(
        FakeIdentityRepository(
            LocalUserIdentity(
                principal_id=uuid4(),
                is_active=False,
                deleted_at=datetime.now(timezone.utc),
            )
        ),
        FailingUowFactory(),
        FakePolicy(jit_enabled=False),
    )

    with pytest.raises(LocalIdentityRetired):
        await resolver.resolve(make_identity())


@pytest.mark.asyncio
async def test_resolve_provisions_new_identity_when_jit_enabled() -> None:
    principal_id = uuid4()
    provisioning_repository = FakeProvisioningRepository(
        recheck_result=None,
        provisioned_principal_id=principal_id,
    )
    uow = FakeUnitOfWork(provisioning_repository)

    resolver = IdentityResolver(
        FakeIdentityRepository(None),
        lambda: uow,
        FakePolicy(jit_enabled=True),
    )

    identity = make_identity()
    result = await resolver.resolve(identity)

    assert result == principal_id
    assert provisioning_repository.provision_calls == [identity]
    assert uow.committed is True
    assert uow.entered is True
    assert uow.exited is True
    assert provisioning_repository.lookup_calls == [
        (identity.issuer, identity.subject)
    ]


@pytest.mark.asyncio
async def test_resolve_uses_recheck_result_on_provisioning_race() -> None:
    principal_id = uuid4()
    provisioning_repository = FakeProvisioningRepository(
        recheck_result=LocalUserIdentity(
            principal_id=principal_id,
            is_active=True,
            deleted_at=None,
        ),
    )
    uow = FakeUnitOfWork(provisioning_repository)

    resolver = IdentityResolver(
        FakeIdentityRepository(None),
        lambda: uow,
        FakePolicy(jit_enabled=True),
    )

    result = await resolver.resolve(make_identity())

    assert result == principal_id
    assert provisioning_repository.provision_calls == []
    assert uow.committed is False
    assert provisioning_repository.lookup_calls == [
        (make_identity().issuer, make_identity().subject)
    ]


@pytest.mark.asyncio
async def test_resolve_rejects_retired_principal_found_on_recheck() -> None:
    provisioning_repository = FakeProvisioningRepository(
        recheck_result=LocalUserIdentity(
            principal_id=uuid4(),
            is_active=False,
            deleted_at=datetime.now(timezone.utc),
        ),
    )
    uow = FakeUnitOfWork(provisioning_repository)

    resolver = IdentityResolver(
        FakeIdentityRepository(None),
        lambda: uow,
        FakePolicy(jit_enabled=True),
    )

    with pytest.raises(LocalIdentityRetired):
        await resolver.resolve(make_identity())

    assert provisioning_repository.provision_calls == []


@pytest.mark.asyncio
async def test_resolve_recovers_winner_after_provisioning_conflict() -> None:
    """Two concurrent first logins: this resolver loses the unique-constraint
    race in the first UOW, rolls back, opens a *second* fresh UOW, and must
    return the winner's principal_id rather than propagating the conflict."""
    principal_id = uuid4()

    losing_repository = FakeProvisioningRepository(conflict=True)
    events: list[str] = []
    losing_uow = FakeUnitOfWork(losing_repository, name="losing", events=events)

    winning_repository = FakeProvisioningRepository(
        recheck_result=LocalUserIdentity(
            principal_id=principal_id,
            is_active=True,
            deleted_at=None,
        ),
    )
    retry_uow = FakeUnitOfWork(winning_repository, name="retry", events=events)

    uow_factory = SequencedUowFactory([losing_uow, retry_uow])

    resolver = IdentityResolver(
        FakeIdentityRepository(None),
        uow_factory,
        FakePolicy(jit_enabled=True),
    )

    result = await resolver.resolve(make_identity())

    assert result == principal_id
    assert uow_factory.calls == 2
    assert losing_uow.committed is False
    assert losing_uow.exited is True
    assert losing_uow.rolled_back is True
    assert events.index("losing:exit") < events.index("retry:enter")
    assert winning_repository.lookup_calls == [
        (make_identity().issuer, make_identity().subject)
    ]
    assert winning_repository.provision_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_active", "deleted_at", "expected_error"),
    [
        (False, None, LocalIdentityDisabled),
        (False, datetime.now(timezone.utc), LocalIdentityRetired),
    ],
)
async def test_resolve_validates_winning_principal_lifecycle_after_conflict(
    is_active: bool,
    deleted_at: datetime | None,
    expected_error: type[LocalIdentityDisabled],
) -> None:
    losing_repository = FakeProvisioningRepository(conflict=True)
    losing_uow = FakeUnitOfWork(losing_repository)

    winning_repository = FakeProvisioningRepository(
        recheck_result=LocalUserIdentity(
            principal_id=uuid4(),
            is_active=is_active,
            deleted_at=deleted_at,
        )
    )
    winning_uow = FakeUnitOfWork(winning_repository)

    resolver = IdentityResolver(
        FakeIdentityRepository(None),
        SequencedUowFactory([losing_uow, winning_uow]),
        FakePolicy(jit_enabled=True),
    )

    with pytest.raises(expected_error):
        await resolver.resolve(make_identity())

    assert losing_uow.rolled_back is True
    assert winning_repository.provision_calls == []


@pytest.mark.asyncio
async def test_resolve_does_not_catch_non_recoverable_provisioning_errors() -> None:
    provisioning_error = RuntimeError("provisioning failed")
    provisioning_repository = FakeProvisioningRepository(
        provision_error=provisioning_error,
    )
    uow = FakeUnitOfWork(provisioning_repository)

    resolver = IdentityResolver(
        FakeIdentityRepository(None),
        lambda: uow,
        FakePolicy(jit_enabled=True),
    )

    with pytest.raises(RuntimeError, match="provisioning failed"):
        await resolver.resolve(make_identity())

    assert uow.exited is True
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_resolve_raises_conflict_when_no_winner_found_after_collision() -> None:
    losing_repository = FakeProvisioningRepository(conflict=True)
    losing_uow = FakeUnitOfWork(losing_repository)

    retry_repository = FakeProvisioningRepository(recheck_result=None)
    retry_uow = FakeUnitOfWork(retry_repository)

    uow_factory = SequencedUowFactory([losing_uow, retry_uow])

    resolver = IdentityResolver(
        FakeIdentityRepository(None),
        uow_factory,
        FakePolicy(jit_enabled=True),
    )

    with pytest.raises(IdentityProvisioningConflict):
        await resolver.resolve(make_identity())

    assert uow_factory.calls == 2
    assert losing_uow.committed is False
    assert losing_uow.rolled_back is True
