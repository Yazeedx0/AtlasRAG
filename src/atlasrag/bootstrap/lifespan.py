from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from atlasrag.bootstrap.core.config import get_settings
from atlasrag.platform.auth.keycloak import KeycloakTokenVerifier
from atlasrag.platform.storage import MinioObjectStorage

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    verifier = KeycloakTokenVerifier(
        issuer=str(settings.KEYCLOAK_ISSUER),
        discovery_url=str(settings.KEYCLOAK_DISCOVERY_URL),
        audience=settings.KEYCLOAK_AUDIENCE,
        algorithms=settings.KEYCLOAK_ALGORITHMS,
        timeout_seconds=settings.KEYCLOAK_TIMEOUT_SECONDS,
        jwks_cache_ttl_seconds=settings.KEYCLOAK_JWKS_CACHE_TTL_SECONDS,
        jwks_refresh_cooldown_seconds=settings.KEYCLOAK_JWKS_REFRESH_COOLDOWN_SECONDS,
    )
    application.state.token_verifier = verifier
    application.state.object_storage = MinioObjectStorage(
        endpoint_url=settings.MINIO_ENDPOINT_URL,
        use_ssl=settings.MINIO_USE_SSL,
        access_key=settings.MINIO_ROOT_USER,
        secret_key=settings.MINIO_ROOT_PASSWORD,
        bucket=settings.MINIO_BUCKET,
        region=settings.MINIO_REGION,
    )
    try:
        yield
    finally:
        await verifier.aclose()
