from uuid import UUID, uuid4

import pytest
from apps.api.dependencies.permissions import require_permission
from fastapi import HTTPException, status

from atlasrag.contracts.permission_errors import PermissionDenied
from atlasrag.contracts.permissions import Permission


class FakePermissionAuthorizationService:
    def __init__(self, *, denied: bool) -> None:
        self.denied = denied
        self.calls: list[tuple[UUID, Permission]] = []

    async def require(
        self,
        *,
        user_principal_id: UUID,
        permission: Permission,
    ) -> None:
        self.calls.append((user_principal_id, permission))
        if self.denied:
            raise PermissionDenied(
                actor_principal_id=user_principal_id,
                permission=permission,
            )


@pytest.mark.asyncio
async def test_permission_dependency_returns_authorized_principal() -> None:
    user_id = uuid4()
    service = FakePermissionAuthorizationService(denied=False)
    dependency = require_permission(Permission.IAM_GROUPS_MANAGE)

    result = await dependency(
        user_principal_id=user_id,
        authorization_service=service,
    )

    assert result == user_id
    assert service.calls == [(user_id, Permission.IAM_GROUPS_MANAGE)]


@pytest.mark.asyncio
async def test_permission_dependency_maps_denial_to_403_without_context_leak() -> None:
    user_id = uuid4()
    service = FakePermissionAuthorizationService(denied=True)
    dependency = require_permission(Permission.IAM_GROUPS_MANAGE)

    with pytest.raises(HTTPException) as raised:
        await dependency(
            user_principal_id=user_id,
            authorization_service=service,
        )

    assert raised.value.status_code == status.HTTP_403_FORBIDDEN
    assert raised.value.detail == "Insufficient permissions"
    assert str(user_id) not in raised.value.detail
