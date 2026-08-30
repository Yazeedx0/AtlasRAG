from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from atlasrag.contracts.types.identity_types import PrincipalState
from atlasrag.contracts.error.permission_errors import (
    PermissionGrantConflict,
    PermissionGrantNotFound,
    PermissionNotFound,
    PermissionTargetInactive,
    PermissionTargetNotFound,
    PermissionTargetRetired,
    ProtectedSuperadminRole,
)
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.services.permission_management import (
    PermissionManagementService,
)

_NOW = datetime(2026, 8, 30, tzinfo=UTC)


class FakePrincipalRepository:
    def __init__(self, principal: PrincipalState | None) -> None:
        self.principal = principal
        self.calls: list[UUID] = []

    async def find_by_id(self, principal_id: UUID) -> PrincipalState | None:
        self.calls.append(principal_id)
        return self.principal


class FakePermissionRepository:
    def __init__(
        self,
        *,
        registered: bool = True,
        has_active_grant: bool = False,
        revoke_result: bool = True,
        add_error: BaseException | None = None,
    ) -> None:
        self.registered = registered
        self.active_grant = has_active_grant
        self.revoke_result = revoke_result
        self.add_error = add_error
        self.add_calls: list[tuple[UUID, Permission, UUID | None, datetime]] = []
        self.revoke_calls: list[tuple[UUID, Permission, UUID | None, datetime]] = []

    async def permission_exists(self, permission: Permission) -> bool:
        return self.registered

    async def has_active_grant(
        self,
        *,
        principal_id: UUID,
        permission: Permission,
    ) -> bool:
        return self.active_grant

    async def add_grant(
        self,
        *,
        principal_id: UUID,
        permission: Permission,
        granted_by_principal_id: UUID | None,
        granted_at: datetime,
    ) -> None:
        if self.add_error is not None:
            raise self.add_error
        self.add_calls.append(
            (principal_id, permission, granted_by_principal_id, granted_at)
        )

    async def revoke_active_grant(
        self,
        *,
        principal_id: UUID,
        permission: Permission,
        revoked_by_principal_id: UUID | None,
        revoked_at: datetime,
    ) -> bool:
        self.revoke_calls.append(
            (principal_id, permission, revoked_by_principal_id, revoked_at)
        )
        return self.revoke_result


class FakeSuperadminRepository:
    def __init__(self, role_id: UUID) -> None:
        self.role_id = role_id

    async def find_superadmin_role_id(self) -> UUID | None:
        return self.role_id


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        principal: PrincipalState | None,
        permissions: FakePermissionRepository,
        superadmin_role_id: UUID,
        commit_error: BaseException | None = None,
    ) -> None:
        self.principals = FakePrincipalRepository(principal)
        self.permissions = permissions
        self.superadmins = FakeSuperadminRepository(superadmin_role_id)
        self.commit_error = commit_error
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
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True


def make_service(
    *,
    principal: PrincipalState | None,
    permissions: FakePermissionRepository | None = None,
    superadmin_role_id: UUID | None = None,
    commit_error: BaseException | None = None,
) -> tuple[PermissionManagementService, FakeUnitOfWork, FakePermissionRepository]:
    permission_repository = permissions or FakePermissionRepository()
    uow = FakeUnitOfWork(
        principal=principal,
        permissions=permission_repository,
        superadmin_role_id=superadmin_role_id or uuid4(),
        commit_error=commit_error,
    )
    service = PermissionManagementService(
        lambda: uow,  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )
    return service, uow, permission_repository


def active_principal(principal_id: UUID) -> PrincipalState:
    return PrincipalState(
        principal_id=principal_id,
        is_active=True,
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_grant_permission_adds_temporal_grant_and_commits() -> None:
    principal_id = uuid4()
    actor_id = uuid4()
    service, uow, repository = make_service(principal=active_principal(principal_id))

    await service.grant_permission(
        principal_id=principal_id,
        permission=Permission.IAM_GROUPS_MANAGE,
        actor_principal_id=actor_id,
    )

    assert repository.add_calls == [
        (principal_id, Permission.IAM_GROUPS_MANAGE, actor_id, _NOW)
    ]
    assert uow.committed is True


@pytest.mark.asyncio
async def test_grant_permission_rejects_duplicate_active_grant() -> None:
    principal_id = uuid4()
    repository = FakePermissionRepository(has_active_grant=True)
    service, uow, _ = make_service(
        principal=active_principal(principal_id),
        permissions=repository,
    )

    with pytest.raises(PermissionGrantConflict):
        await service.grant_permission(
            principal_id=principal_id,
            permission=Permission.IAM_GROUPS_MANAGE,
            actor_principal_id=uuid4(),
        )

    assert repository.add_calls == []
    assert uow.committed is False
    assert uow.rolled_back is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("principal", "error_type"),
    [
        (None, PermissionTargetNotFound),
        (
            PrincipalState(principal_id=uuid4(), is_active=False, deleted_at=None),
            PermissionTargetInactive,
        ),
        (
            PrincipalState(
                principal_id=uuid4(),
                is_active=False,
                deleted_at=_NOW,
            ),
            PermissionTargetRetired,
        ),
    ],
)
async def test_grant_permission_rejects_unusable_target(
    principal: PrincipalState | None,
    error_type: type[Exception],
) -> None:
    service, uow, repository = make_service(principal=principal)

    with pytest.raises(error_type):
        await service.grant_permission(
            principal_id=uuid4(),
            permission=Permission.IAM_GROUPS_MANAGE,
            actor_principal_id=uuid4(),
        )

    assert repository.add_calls == []
    assert uow.committed is False


@pytest.mark.asyncio
async def test_grant_permission_rejects_unregistered_permission() -> None:
    principal_id = uuid4()
    repository = FakePermissionRepository(registered=False)
    service, _, _ = make_service(
        principal=active_principal(principal_id),
        permissions=repository,
    )

    with pytest.raises(PermissionNotFound):
        await service.grant_permission(
            principal_id=principal_id,
            permission=Permission.IAM_GROUPS_MANAGE,
            actor_principal_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_grant_permission_maps_commit_race_to_conflict_and_rolls_back() -> None:
    principal_id = uuid4()
    integrity_error = IntegrityError("insert", {}, Exception("duplicate"))
    service, uow, _ = make_service(
        principal=active_principal(principal_id),
        commit_error=integrity_error,
    )

    with pytest.raises(PermissionGrantConflict):
        await service.grant_permission(
            principal_id=principal_id,
            permission=Permission.IAM_GROUPS_MANAGE,
            actor_principal_id=uuid4(),
        )

    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_grant_permission_propagates_repository_error_and_rolls_back() -> None:
    principal_id = uuid4()
    repository = FakePermissionRepository(add_error=RuntimeError("write failed"))
    service, uow, _ = make_service(
        principal=active_principal(principal_id),
        permissions=repository,
    )

    with pytest.raises(RuntimeError, match="write failed"):
        await service.grant_permission(
            principal_id=principal_id,
            permission=Permission.IAM_GROUPS_MANAGE,
            actor_principal_id=uuid4(),
        )

    assert uow.rolled_back is True
    assert uow.committed is False


@pytest.mark.asyncio
async def test_revoke_permission_closes_active_grant_and_commits() -> None:
    principal_id = uuid4()
    actor_id = uuid4()
    service, uow, repository = make_service(principal=active_principal(principal_id))

    await service.revoke_permission(
        principal_id=principal_id,
        permission=Permission.IAM_GROUPS_MANAGE,
        actor_principal_id=actor_id,
    )

    assert repository.revoke_calls == [
        (principal_id, Permission.IAM_GROUPS_MANAGE, actor_id, _NOW)
    ]
    assert uow.committed is True


@pytest.mark.asyncio
async def test_revoke_permission_rejects_missing_grant() -> None:
    principal_id = uuid4()
    repository = FakePermissionRepository(revoke_result=False)
    service, uow, _ = make_service(
        principal=active_principal(principal_id),
        permissions=repository,
    )

    with pytest.raises(PermissionGrantNotFound):
        await service.revoke_permission(
            principal_id=principal_id,
            permission=Permission.IAM_GROUPS_MANAGE,
            actor_principal_id=uuid4(),
        )

    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_revoke_permission_rejects_superadmin_role() -> None:
    role_id = uuid4()
    service, uow, repository = make_service(
        principal=active_principal(role_id),
        superadmin_role_id=role_id,
    )

    with pytest.raises(ProtectedSuperadminRole):
        await service.revoke_permission(
            principal_id=role_id,
            permission=Permission.IAM_GROUPS_MANAGE,
            actor_principal_id=uuid4(),
        )

    assert repository.revoke_calls == []
    assert uow.rolled_back is True
