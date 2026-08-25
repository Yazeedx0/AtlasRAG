from datetime import datetime, timezone
from uuid import uuid4

import pytest

from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.identity import LocalUserIdentity
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

    async def find_by_oidc_subject(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> LocalUserIdentity | None:
        return self._result


class FakePolicy:
    def __init__(self, *, jit_enabled: bool) -> None:
        self._jit_enabled = jit_enabled

    def jit_enabled(self) -> bool:
        return self._jit_enabled


class FailingUowFactory:
    def __call__(self):
        raise AssertionError("uow_factory should not be called on this path")


class FakeProvisioningRepository:
    def __init__(
        self,
        *,
        recheck_result: LocalUserIdentity | None = None,
        provisioned_principal_id=None,
        conflict: bool = False,
    ) -> None:
        self._recheck_result = recheck_result
        self.provisioned_principal_id = provisioned_principal_id
        self._conflict = conflict
        self.provision_calls: list[AuthenticatedIdentity] = []

    async def find_by_oidc_subject(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> LocalUserIdentity | None:
        return self._recheck_result

    async def provision_user(self, identity: AuthenticatedIdentity):
        self.provision_calls.append(identity)
        if self._conflict:
            raise IdentityAlreadyProvisioned
        return self.provisioned_principal_id


class FakeUnitOfWork:
    def __init__(self, identities: FakeProvisioningRepository) -> None:
        self.identities = identities
        self.committed = False
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.exited = True

    async def commit(self) -> None:
        self.committed = True


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

    result = await resolver.resolve(make_identity())

    assert result == principal_id


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
    losing_uow = FakeUnitOfWork(losing_repository)

    winning_repository = FakeProvisioningRepository(
        recheck_result=LocalUserIdentity(
            principal_id=principal_id,
            is_active=True,
            deleted_at=None,
        ),
    )
    retry_uow = FakeUnitOfWork(winning_repository)

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
    assert winning_repository.provision_calls == []


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
