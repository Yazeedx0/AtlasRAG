from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from apps.api.dependencies.identity import (
    get_local_principal_id,
    get_principal_lifecycle,
)
from apps.api.dependencies.permissions import get_permission_authorization_service
from apps.api.router import api_router
from apps.api.utilities.exception_handlers import register_exception_handlers

from atlasrag.contracts.identity_errors import (
    PrincipalNotFound,
    PrincipalRetired,
)
from atlasrag.contracts.permission_errors import (
    LastSuperadminViolation,
    PermissionDenied,
    ProtectedSuperadminRole,
)
from atlasrag.contracts.permissions import Permission

_ACTOR_ID = uuid4()
_TARGET_ID = uuid4()


class FakePermissionAuthorizationService:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[tuple[UUID, Permission]] = []

    async def require(
        self,
        *,
        user_principal_id: UUID,
        permission: Permission,
    ) -> None:
        self.calls.append((user_principal_id, permission))
        if not self.allowed:
            raise PermissionDenied(
                actor_principal_id=user_principal_id,
                permission=permission,
            )


class FakePrincipalLifecycle:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, UUID]] = []

    async def activate_principal(self, principal_id: UUID) -> None:
        await self._record("activate", principal_id)

    async def deactivate_principal(self, principal_id: UUID) -> None:
        await self._record("deactivate", principal_id)

    async def retire_principal(self, principal_id: UUID) -> None:
        await self._record("retire", principal_id)

    async def _record(self, operation: str, principal_id: UUID) -> None:
        self.calls.append((operation, principal_id))
        if self.error is not None:
            raise self.error


def make_app(
    *,
    permission_allowed: bool = True,
    lifecycle: FakePrincipalLifecycle | None = None,
) -> tuple[FastAPI, FakePermissionAuthorizationService, FakePrincipalLifecycle]:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(api_router)

    authorization = FakePermissionAuthorizationService(
        allowed=permission_allowed,
    )
    lifecycle_service = lifecycle or FakePrincipalLifecycle()

    application.dependency_overrides[get_local_principal_id] = lambda: _ACTOR_ID
    application.dependency_overrides[
        get_permission_authorization_service
    ] = lambda: authorization
    application.dependency_overrides[get_principal_lifecycle] = lambda: lifecycle_service
    return application, authorization, lifecycle_service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "path_suffix"),
    [
        ("activate", "activate"),
        ("deactivate", "deactivate"),
        ("retire", "retire"),
    ],
)
async def test_principal_lifecycle_endpoints_return_204_and_call_service(
    operation: str,
    path_suffix: str,
) -> None:
    application, authorization, lifecycle = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/iam/principals/{_TARGET_ID}/{path_suffix}"
        )

    assert response.status_code == 204
    assert response.content == b""
    assert authorization.calls == [
        (_ACTOR_ID, Permission.IAM_PRINCIPALS_MANAGE),
    ]
    assert lifecycle.calls == [(operation, _TARGET_ID)]


@pytest.mark.asyncio
@pytest.mark.parametrize("path_suffix", ["activate", "deactivate", "retire"])
async def test_principal_lifecycle_endpoints_require_manage_permission(
    path_suffix: str,
) -> None:
    application, authorization, lifecycle = make_app(permission_allowed=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/iam/principals/{_TARGET_ID}/{path_suffix}"
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions"}
    assert authorization.calls == [
        (_ACTOR_ID, Permission.IAM_PRINCIPALS_MANAGE),
    ]
    assert lifecycle.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            PrincipalNotFound(principal_id=_TARGET_ID, role="principal"),
            404,
        ),
        (
            PrincipalRetired(principal_id=_TARGET_ID, role="principal"),
            409,
        ),
        (
            ProtectedSuperadminRole(operation="deactivate principal"),
            409,
        ),
        (
            LastSuperadminViolation(
                user_principal_id=_TARGET_ID,
                operation="deactivate principal",
            ),
            409,
        ),
    ],
)
async def test_principal_lifecycle_domain_errors_are_mapped_centrally(
    error: Exception,
    expected_status: int,
) -> None:
    lifecycle = FakePrincipalLifecycle(error=error)
    application, _, lifecycle = make_app(lifecycle=lifecycle)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/iam/principals/{_TARGET_ID}/deactivate"
        )

    assert response.status_code == expected_status
    assert response.json() == {"detail": str(error)}
    assert lifecycle.calls == [("deactivate", _TARGET_ID)]


@pytest.mark.asyncio
async def test_principal_lifecycle_endpoints_reject_invalid_principal_uuid() -> None:
    application, authorization, lifecycle = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            "/api/v1/iam/principals/not-a-uuid/activate"
        )

    assert response.status_code == 422
    assert authorization.calls == [
        (_ACTOR_ID, Permission.IAM_PRINCIPALS_MANAGE),
    ]
    assert lifecycle.calls == []
