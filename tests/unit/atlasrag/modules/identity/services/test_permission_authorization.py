from collections.abc import Collection
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.permission_errors import PermissionDenied
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.services.permission_authorization import (
    PermissionAuthorizationService,
)

_NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


class FakeEffectivePrincipalResolver:
    def __init__(self, principal_ids: frozenset[UUID]) -> None:
        self._principal_ids = principal_ids
        self.calls: list[UUID] = []

    async def resolve_effective_principal_ids(
        self,
        user_principal_id: UUID,
    ) -> frozenset[UUID]:
        self.calls.append(user_principal_id)
        return self._principal_ids


class FakePermissionRepository:
    def __init__(self, result: bool) -> None:
        self._result = result
        self.calls: list[tuple[Collection[UUID], Permission, datetime]] = []

    async def has_permission(
        self,
        *,
        principal_ids: Collection[UUID],
        permission: Permission,
        at: datetime,
    ) -> bool:
        self.calls.append((principal_ids, permission, at))
        return self._result


def make_service(
    *,
    result: bool,
) -> tuple[
    PermissionAuthorizationService,
    FakeEffectivePrincipalResolver,
    FakePermissionRepository,
]:
    resolver = FakeEffectivePrincipalResolver(frozenset({uuid4(), uuid4()}))
    repository = FakePermissionRepository(result)
    service = PermissionAuthorizationService(
        effective_principal_resolver=resolver,
        permission_repository=repository,
        clock=lambda: _NOW,
    )
    return service, resolver, repository


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
async def test_is_allowed_resolves_effective_principals_and_returns_decision(
    allowed: bool,
) -> None:
    user_id = uuid4()
    service, resolver, repository = make_service(result=allowed)

    result = await service.is_allowed(
        user_principal_id=user_id,
        permission=Permission.IAM_GROUPS_MANAGE,
    )

    assert result is allowed
    assert resolver.calls == [user_id]
    assert repository.calls == [
        (
            resolver._principal_ids,
            Permission.IAM_GROUPS_MANAGE,
            _NOW,
        )
    ]


@pytest.mark.asyncio
async def test_require_returns_for_allowed_permission() -> None:
    user_id = uuid4()
    service, _, _ = make_service(result=True)

    await service.require(
        user_principal_id=user_id,
        permission=Permission.IAM_ROLES_MANAGE,
    )


@pytest.mark.asyncio
async def test_require_raises_contextual_permission_denied() -> None:
    user_id = uuid4()
    service, _, _ = make_service(result=False)

    with pytest.raises(PermissionDenied) as raised:
        await service.require(
            user_principal_id=user_id,
            permission=Permission.IAM_ROLES_MANAGE,
        )

    assert raised.value.actor_principal_id == user_id
    assert raised.value.permission is Permission.IAM_ROLES_MANAGE
