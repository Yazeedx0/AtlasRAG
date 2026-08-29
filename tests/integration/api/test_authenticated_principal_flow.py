from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from apps.api.dependencies.identity import get_identity_resolver
from apps.api.router import api_router
from atlasrag.bootstrap.identity import ConfiguredProvisioningPolicy
from atlasrag.modules.identity.enums import IdentifierType, PrincipalType
from atlasrag.modules.identity.models import Principal, UserIdentifier, Users
from atlasrag.modules.identity.repositories.identity import (
    SqlAlchemyIdentityRepository,
)
from atlasrag.modules.identity.repositories.unit_of_work import (
    make_identity_unit_of_work_factory,
)
from atlasrag.modules.identity.services.identity_resolver import IdentityResolver
from atlasrag.modules.identity.services.principal_lifecycle import PrincipalLifecycle
from atlasrag.platform.auth.keycloak import KeycloakTokenVerifier
from atlasrag.platform.database import Base

ISSUER = "https://auth.example.com/realms/atlasrag"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
AUDIENCE = "atlasrag-api"
KEY_ID = "integration-signing-key"
SUBJECT = "keycloak-user-123"


@dataclass(frozen=True, slots=True)
class SigningMaterial:
    private_key: RSAPrivateKey
    public_jwk: Mapping[str, object]


@dataclass(slots=True)
class AuthApiHarness:
    client: httpx.AsyncClient
    signing_material: SigningMaterial
    oidc_requests: list[str]
    session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture
def signing_material() -> SigningMaterial:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
        private_key.public_key(),
        as_dict=True,
    )
    public_jwk.update(
        {
            "kid": KEY_ID,
            "alg": "RS256",
            "use": "sig",
        }
    )
    return SigningMaterial(private_key=private_key, public_jwk=public_jwk)


def make_access_token(
    signing_material: SigningMaterial,
    *,
    private_key: RSAPrivateKey | None = None,
    claim_overrides: Mapping[str, object] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": SUBJECT,
        "aud": AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
        "email": "user@example.com",
        "email_verified": True,
        "preferred_username": "integration-user",
        "name": "Integration User",
    }
    if claim_overrides is not None:
        claims.update(claim_overrides)

    return jwt.encode(
        claims,
        private_key or signing_material.private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )


@pytest_asyncio.fixture
async def auth_api(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    signing_material: SigningMaterial,
) -> AsyncIterator[AuthApiHarness]:
    _, session_factory = identity_database
    oidc_requests: list[str] = []

    def oidc_handler(request: httpx.Request) -> httpx.Response:
        oidc_requests.append(str(request.url))
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json={"jwks_uri": JWKS_URL})
        if str(request.url) == JWKS_URL:
            keys = [dict(signing_material.public_jwk)]
            return httpx.Response(200, json={"keys": keys})
        return httpx.Response(404)

    oidc_client = httpx.AsyncClient(transport=httpx.MockTransport(oidc_handler))
    verifier = KeycloakTokenVerifier(
        issuer=ISSUER,
        discovery_url=DISCOVERY_URL,
        audience=AUDIENCE,
        algorithms=("RS256",),
        timeout_seconds=1.0,
        jwks_cache_ttl_seconds=300.0,
        jwks_refresh_cooldown_seconds=1.0,
        http_client=oidc_client,
    )

    async def override_identity_resolver() -> AsyncIterator[IdentityResolver]:
        async with session_factory() as lookup_session:
            yield IdentityResolver(
                repository=SqlAlchemyIdentityRepository(lookup_session),
                uow_factory=make_identity_unit_of_work_factory(session_factory),
                policy=ConfiguredProvisioningPolicy(enabled=True),
            )

    application = FastAPI()
    application.include_router(api_router)
    application.state.token_verifier = verifier
    application.dependency_overrides[get_identity_resolver] = override_identity_resolver

    transport = httpx.ASGITransport(app=application)
    async with oidc_client, httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as api_client:
        yield AuthApiHarness(
            client=api_client,
            signing_material=signing_material,
            oidc_requests=oidc_requests,
            session_factory=session_factory,
        )

    application.dependency_overrides.clear()


async def count_rows(engine: AsyncEngine, model: type[Base]) -> int:
    async with engine.connect() as connection:
        result = await connection.scalar(select(func.count()).select_from(model))
    assert result is not None
    return int(result)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_valid_access_token_resolves_and_reuses_local_principal(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    auth_api: AuthApiHarness,
) -> None:
    engine, _ = identity_database
    token = make_access_token(auth_api.signing_material)

    first_response = await auth_api.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert first_response.status_code == 200
    first_body = first_response.json()
    principal_id = UUID(first_body["principal_id"])
    assert first_body == {
        "principal_id": str(principal_id),
        "issuer": ISSUER,
        "subject": SUBJECT,
        "email": "user@example.com",
        "email_verified": True,
        "username": "integration-user",
        "display_name": "Integration User",
    }

    async with engine.connect() as connection:
        identity_projection = (
            await connection.execute(
                select(
                    Principal.id,
                    Principal.type,
                    Principal.is_active,
                    Principal.deleted_at,
                    Users.display_name,
                    UserIdentifier.identifier_type,
                    UserIdentifier.issuer,
                    UserIdentifier.normalized_value,
                )
                .join(Users, Users.principal_id == Principal.id)
                .join(
                    UserIdentifier,
                    UserIdentifier.user_principal_id == Users.principal_id,
                )
                .where(Principal.id == principal_id)
            )
        ).one()

    assert identity_projection.id == principal_id
    assert identity_projection.type == PrincipalType.USER
    assert identity_projection.is_active is True
    assert identity_projection.deleted_at is None
    assert identity_projection.display_name == "Integration User"
    assert identity_projection.identifier_type == IdentifierType.OIDC_SUBJECT.value
    assert identity_projection.issuer == ISSUER
    assert identity_projection.normalized_value == SUBJECT

    second_response = await auth_api.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert second_response.status_code == 200
    assert second_response.json()["principal_id"] == str(principal_id)
    assert await count_rows(engine, Principal) == 1
    assert await count_rows(engine, Users) == 1
    assert await count_rows(engine, UserIdentifier) == 1
    assert auth_api.oidc_requests == [DISCOVERY_URL, JWKS_URL]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iss": "https://untrusted.example.com/realms/atlasrag"},
        {"aud": "another-api"},
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
    ],
    ids=["wrong-issuer", "wrong-audience", "expired"],
)
async def test_untrusted_token_returns_401_without_provisioning_principal(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    auth_api: AuthApiHarness,
    claim_overrides: Mapping[str, object],
) -> None:
    engine, _ = identity_database
    token = make_access_token(
        auth_api.signing_material,
        claim_overrides=claim_overrides,
    )

    response = await auth_api.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication token"}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert await count_rows(engine, Principal) == 0
    assert await count_rows(engine, Users) == 0
    assert await count_rows(engine, UserIdentifier) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invalid_signature_returns_401_without_provisioning_principal(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    auth_api: AuthApiHarness,
) -> None:
    engine, _ = identity_database
    untrusted_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_access_token(
        auth_api.signing_material,
        private_key=untrusted_private_key,
    )

    response = await auth_api.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication token"}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert await count_rows(engine, Principal) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disabled_principal_returns_403_after_successful_authentication(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    auth_api: AuthApiHarness,
) -> None:
    engine, _ = identity_database
    token = make_access_token(auth_api.signing_material)
    initial_response = await auth_api.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert initial_response.status_code == 200
    principal_id = UUID(initial_response.json()["principal_id"])

    lifecycle = PrincipalLifecycle(
        make_identity_unit_of_work_factory(auth_api.session_factory),
    )
    await lifecycle.deactivate_principal(principal_id)

    response = await auth_api.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Authenticated identity has no usable local access",
    }
    assert await count_rows(engine, Principal) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_bearer_token_returns_401_without_oidc_or_principal_provisioning(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    auth_api: AuthApiHarness,
) -> None:
    engine, _ = identity_database

    response = await auth_api.client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert auth_api.oidc_requests == []
    assert await count_rows(engine, Principal) == 0
