"""Print an access token for the seeded development user."""

import argparse
import asyncio
import os
from dataclasses import dataclass

import httpx

from atlasrag.bootstrap.core.config import Settings, get_settings

DEV_CLI_CLIENT_ID = "atlasrag-cli"


@dataclass(frozen=True, slots=True)
class TokenConfig:
    keycloak_url: str
    realm: str
    client_id: str
    username: str
    password: str


def _keycloak_endpoint(settings: Settings) -> tuple[str, str]:
    issuer = str(settings.KEYCLOAK_ISSUER).rstrip("/")
    base_url, separator, realm = issuer.rpartition("/realms/")
    if not separator or not base_url or not realm:
        raise RuntimeError("KEYCLOAK_ISSUER must end with /realms/<realm>")
    return base_url, realm


async def _request_token(config: TokenConfig) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{config.keycloak_url}/realms/{config.realm}"
            "/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": config.client_id,
                "username": config.username,
                "password": config.password,
                "scope": "openid",
            },
        )

    if response.status_code != 200:
        description = _error_description(response)
        raise RuntimeError(
            f"Keycloak token request failed with status {response.status_code}: "
            f"{description}"
        )

    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Keycloak token response returned an unexpected JSON payload")

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Keycloak token response did not contain an access token")
    return access_token


def _error_description(response: httpx.Response) -> str:
    payload = response.json()
    if isinstance(payload, dict):
        description = payload.get("error_description")
        if isinstance(description, str) and description:
            return description
    return "unknown Keycloak error"


def _parse_args(settings: Settings) -> TokenConfig:
    default_url, default_realm = _keycloak_endpoint(settings)
    parser = argparse.ArgumentParser(
        description="Print an access token for the AtlasRAG development user."
    )
    parser.add_argument(
        "--keycloak-url",
        default=os.getenv("ATLAS_KEYCLOAK_URL", default_url),
    )
    parser.add_argument(
        "--realm",
        default=os.getenv("ATLAS_KEYCLOAK_REALM", default_realm),
    )
    parser.add_argument("--client-id", default=DEV_CLI_CLIENT_ID)
    parser.add_argument(
        "--username",
        default=os.getenv("ATLAS_SEED_USER_USERNAME", settings.SEED_USER_USERNAME),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("ATLAS_SEED_USER_PASSWORD", settings.SEED_USER_PASSWORD),
    )
    arguments = parser.parse_args()

    if not arguments.password:
        parser.error("--password or ATLAS_SEED_USER_PASSWORD is required")

    return TokenConfig(
        keycloak_url=arguments.keycloak_url.rstrip("/"),
        realm=arguments.realm,
        client_id=arguments.client_id,
        username=arguments.username,
        password=arguments.password,
    )


def main() -> None:
    settings = get_settings()
    token = asyncio.run(_request_token(_parse_args(settings)))
    print(token)


if __name__ == "__main__":
    main()
