"""Seed a development user in Keycloak and the local AtlasRAG IAM database."""

import argparse
import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.bootstrap.core.config import Settings, get_settings
from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.identity_types import LocalUserIdentity
from atlasrag.modules.identity.repositories.identity import SqlAlchemyIdentityRepository
from scripts.bootstrap_superadmin import bootstrap_superadmin

DEFAULT_KEYCLOAK_ADMIN_USERNAME = "admin"
DEFAULT_SEED_USERNAME = "atlas-admin"
DEFAULT_SEED_EMAIL = "atlas-admin@atlasrag.local"
DEFAULT_SEED_DISPLAY_NAME = "Atlas Admin"
DEV_CLI_CLIENT_ID = "atlasrag-cli"


@dataclass(frozen=True, slots=True)
class SeedConfig:
    keycloak_url: str
    realm: str
    admin_username: str
    admin_password: str
    username: str
    password: str
    email: str
    display_name: str
    first_name: str
    last_name: str
    reset_password: bool


@dataclass(frozen=True, slots=True)
class KeycloakUser:
    user_id: str
    created: bool


def _keycloak_endpoint(settings: Settings) -> tuple[str, str]:
    issuer = str(settings.KEYCLOAK_ISSUER).rstrip("/")
    base_url, separator, realm = issuer.rpartition("/realms/")
    if not separator or not base_url or not realm:
        raise RuntimeError("KEYCLOAK_ISSUER must end with /realms/<realm>")
    return base_url, realm


def _json_object(response: httpx.Response) -> Mapping[str, object]:
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise RuntimeError("Keycloak returned an unexpected JSON object")
    return cast(Mapping[str, object], payload)


async def _get_admin_token(
    client: httpx.AsyncClient,
    *,
    keycloak_url: str,
    admin_username: str,
    admin_password: str,
) -> str:
    response = await client.post(
        f"{keycloak_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": admin_username,
            "password": admin_password,
        },
    )
    if response.status_code != 200:
        raise RuntimeError(
            "Keycloak admin authentication failed "
            f"with status {response.status_code}: {response.text}"
        )

    payload = _json_object(response)
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Keycloak admin response did not contain an access token")
    return access_token


def _admin_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _find_keycloak_user(
    client: httpx.AsyncClient,
    *,
    users_url: str,
    headers: Mapping[str, str],
    username: str,
) -> Mapping[str, object] | None:
    response = await client.get(
        users_url,
        headers=headers,
        params={"username": username, "exact": "true"},
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Keycloak user lookup failed with status {response.status_code}: "
            f"{response.text}"
        )

    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Keycloak user lookup returned an unexpected JSON payload")

    users = [
        cast(Mapping[str, object], user)
        for user in payload
        if isinstance(user, Mapping)
    ]
    if len(users) > 1:
        raise RuntimeError(f"Keycloak returned multiple users for username {username!r}")
    return users[0] if users else None


async def _ensure_keycloak_cli_client(
    client: httpx.AsyncClient,
    *,
    realm_url: str,
    headers: Mapping[str, str],
) -> None:
    clients_url = f"{realm_url}/clients"
    response = await client.get(
        clients_url,
        headers=headers,
        params={"clientId": DEV_CLI_CLIENT_ID, "exact": "true"},
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Keycloak client lookup failed with status {response.status_code}: "
            f"{response.text}"
        )

    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Keycloak client lookup returned an unexpected JSON payload")

    clients = [
        cast(Mapping[str, object], item)
        for item in payload
        if isinstance(item, Mapping)
    ]
    if len(clients) > 1:
        raise RuntimeError(f"Keycloak returned multiple clients for {DEV_CLI_CLIENT_ID!r}")

    client_representation: dict[str, object] = {
        "clientId": DEV_CLI_CLIENT_ID,
        "name": "AtlasRAG Development CLI",
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": True,
        "bearerOnly": False,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": False,
        "authorizationServicesEnabled": False,
        "protocolMappers": [
            {
                "name": "AtlasRAG API audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "consentRequired": False,
                "config": {
                    "included.client.audience": "atlasrag-api",
                    "id.token.claim": "false",
                    "access.token.claim": "true",
                    "userinfo.token.claim": "false",
                },
            }
        ],
    }

    if not clients:
        response = await client.post(
            clients_url,
            headers=headers,
            json=client_representation,
        )
        if response.status_code != 201:
            raise RuntimeError(
                f"Keycloak client creation failed with status {response.status_code}: "
                f"{response.text}"
            )
        return

    client_id = clients[0].get("id")
    if not isinstance(client_id, str) or not client_id:
        raise RuntimeError("Keycloak CLI client does not contain a valid id")

    response = await client.put(
        f"{clients_url}/{client_id}",
        headers=headers,
        json=client_representation,
    )
    if response.status_code != 204:
        raise RuntimeError(
            f"Keycloak client update failed with status {response.status_code}: "
            f"{response.text}"
        )


async def _ensure_keycloak_user(
    client: httpx.AsyncClient,
    *,
    config: SeedConfig,
) -> KeycloakUser:
    realm_url = f"{config.keycloak_url}/admin/realms/{config.realm}"
    headers = _admin_headers(
        await _get_admin_token(
            client,
            keycloak_url=config.keycloak_url,
            admin_username=config.admin_username,
            admin_password=config.admin_password,
        )
    )
    users_url = f"{realm_url}/users"
    await _ensure_keycloak_cli_client(
        client,
        realm_url=realm_url,
        headers=headers,
    )
    existing_user = await _find_keycloak_user(
        client,
        users_url=users_url,
        headers=headers,
        username=config.username,
    )

    if existing_user is None:
        response = await client.post(
            users_url,
            headers=headers,
            json={
                "username": config.username,
                "email": config.email,
                "firstName": config.first_name,
                "lastName": config.last_name,
                "emailVerified": True,
                "enabled": True,
                "requiredActions": [],
                "credentials": [
                    {
                        "type": "password",
                        "value": config.password,
                        "temporary": False,
                    }
                ],
            },
        )
        if response.status_code != 201:
            raise RuntimeError(
                f"Keycloak user creation failed with status {response.status_code}: "
                f"{response.text}"
            )
        existing_user = await _find_keycloak_user(
            client,
            users_url=users_url,
            headers=headers,
            username=config.username,
        )
        if existing_user is None:
            raise RuntimeError("Keycloak created the user but it could not be found afterward")
        created = True
    else:
        created = False

    user_id = existing_user.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise RuntimeError("Keycloak user does not contain a valid id")

    if existing_user.get("enabled") is False:
        raise RuntimeError(f"Keycloak user {config.username!r} is disabled")

    if not created:
        response = await client.put(
            f"{users_url}/{user_id}",
            headers=headers,
            json={
                "id": user_id,
                "username": config.username,
                "email": config.email,
                "firstName": config.first_name,
                "lastName": config.last_name,
                "emailVerified": True,
                "enabled": True,
                "requiredActions": [],
            },
        )
        if response.status_code != 204:
            raise RuntimeError(
                f"Keycloak user setup failed with status {response.status_code}: "
                f"{response.text}"
            )

    if config.reset_password and not created:
        response = await client.put(
            f"{users_url}/{user_id}/reset-password",
            headers=headers,
            json={
                "type": "password",
                "value": config.password,
                "temporary": False,
            },
        )
        if response.status_code != 204:
            raise RuntimeError(
                f"Keycloak password reset failed with status {response.status_code}: "
                f"{response.text}"
            )

    return KeycloakUser(user_id=user_id, created=created)


async def _ensure_local_user(
    *,
    issuer: str,
    subject: str,
    display_name: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, bool]:
    identity = AuthenticatedIdentity(
        issuer=issuer,
        subject=subject,
        display_name=display_name,
    )

    async with session_factory() as session:
        repository = SqlAlchemyIdentityRepository(session)
        existing = await repository.find_by_oidc_subject(
            issuer=issuer,
            subject=subject,
        )
        if existing is not None:
            _ensure_local_identity_is_active(existing)
            return existing.principal_id, False

        principal_id = await repository.provision_user(identity)
        await session.commit()
        return principal_id, True


def _ensure_local_identity_is_active(identity: LocalUserIdentity) -> None:
    if identity.deleted_at is not None or not identity.is_active:
        raise RuntimeError(
            f"Local identity for principal {identity.principal_id} is inactive or retired"
        )


async def _run(config: SeedConfig) -> None:
    settings = get_settings()
    issuer = str(settings.KEYCLOAK_ISSUER).rstrip("/")

    async with httpx.AsyncClient(timeout=10.0) as client:
        keycloak_user = await _ensure_keycloak_user(client, config=config)

    from atlasrag.platform.database.session import async_session_factory

    principal_id, local_user_created = await _ensure_local_user(
        issuer=issuer,
        subject=keycloak_user.user_id,
        display_name=config.display_name,
        session_factory=async_session_factory,
    )
    result = await bootstrap_superadmin(
        issuer=issuer,
        subject=keycloak_user.user_id,
        session_factory=async_session_factory,
    )

    keycloak_action = "created" if keycloak_user.created else "reused"
    local_action = "created" if local_user_created else "reused"
    superadmin_action = "assigned" if result.assigned else "already assigned"
    print(
        f"Keycloak user {keycloak_action}: {config.username} ({keycloak_user.user_id})\n"
        f"Local user {local_action}: {principal_id}\n"
        f"Superadmin role {superadmin_action}: {principal_id}"
    )


def _parse_args(settings: Settings) -> SeedConfig:
    default_keycloak_url, default_realm = _keycloak_endpoint(settings)
    parser = argparse.ArgumentParser(
        description="Seed a development Keycloak user and AtlasRAG superadmin."
    )
    parser.add_argument(
        "--keycloak-url",
        default=os.getenv("ATLAS_KEYCLOAK_URL", default_keycloak_url),
    )
    parser.add_argument(
        "--realm",
        default=os.getenv("ATLAS_KEYCLOAK_REALM", default_realm),
    )
    parser.add_argument(
        "--admin-username",
        default=os.getenv(
            "ATLAS_KEYCLOAK_ADMIN_USERNAME",
            settings.KEYCLOAK_ADMIN_USERNAME or DEFAULT_KEYCLOAK_ADMIN_USERNAME,
        ),
    )
    parser.add_argument(
        "--admin-password",
        default=os.getenv(
            "ATLAS_KEYCLOAK_ADMIN_PASSWORD",
            settings.KEYCLOAK_ADMIN_PASSWORD,
        ),
    )
    parser.add_argument(
        "--username",
        default=os.getenv(
            "ATLAS_SEED_USER_USERNAME",
            settings.SEED_USER_USERNAME or DEFAULT_SEED_USERNAME,
        ),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("ATLAS_SEED_USER_PASSWORD", settings.SEED_USER_PASSWORD),
    )
    parser.add_argument(
        "--email",
        default=os.getenv(
            "ATLAS_SEED_USER_EMAIL",
            settings.SEED_USER_EMAIL or DEFAULT_SEED_EMAIL,
        ),
    )
    parser.add_argument(
        "--display-name",
        default=os.getenv(
            "ATLAS_SEED_USER_DISPLAY_NAME",
            settings.SEED_USER_DISPLAY_NAME or DEFAULT_SEED_DISPLAY_NAME,
        ),
    )
    parser.add_argument(
        "--first-name",
        default=os.getenv("ATLAS_SEED_USER_FIRST_NAME", settings.SEED_USER_FIRST_NAME),
    )
    parser.add_argument(
        "--last-name",
        default=os.getenv("ATLAS_SEED_USER_LAST_NAME", settings.SEED_USER_LAST_NAME),
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Reset the password when the Keycloak user already exists.",
    )
    arguments = parser.parse_args()

    if not arguments.admin_password:
        parser.error(
            "--admin-password or ATLAS_KEYCLOAK_ADMIN_PASSWORD is required"
        )
    if not arguments.password:
        parser.error("--password or ATLAS_SEED_USER_PASSWORD is required")

    return SeedConfig(
        keycloak_url=arguments.keycloak_url.rstrip("/"),
        realm=arguments.realm,
        admin_username=arguments.admin_username,
        admin_password=arguments.admin_password,
        username=arguments.username,
        password=arguments.password,
        email=arguments.email,
        display_name=arguments.display_name,
        first_name=arguments.first_name,
        last_name=arguments.last_name,
        reset_password=arguments.reset_password,
    )


def main() -> None:
    settings = get_settings()
    asyncio.run(_run(_parse_args(settings)))


if __name__ == "__main__":
    main()
