from enum import Enum
from functools import lru_cache

from pydantic import AnyHttpUrl, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    APP_NAME: str = "AtlasRAG"
    APP_VERSION: str = "1.0.0"

    ENVIROMENT: Environment = Environment.DEVELOPMENT

    DATABASE_URL: PostgresDsn
    DATABASE_ECHO: bool = False
    DEBUG: bool = False

    KEYCLOAK_ISSUER: AnyHttpUrl = "http://localhost:8080/realms/atlasrag"
    KEYCLOAK_DISCOVERY_URL: AnyHttpUrl = (
        "http://localhost:8080/realms/atlasrag/.well-known/openid-configuration"
    )
    KEYCLOAK_ADMIN_USERNAME: str = "admin"
    KEYCLOAK_ADMIN_PASSWORD: str | None = None
    KEYCLOAK_AUDIENCE: str = "atlasrag-api"
    KEYCLOAK_ALGORITHMS: tuple[str, ...] = ("RS256",)
    KEYCLOAK_TIMEOUT_SECONDS: float = 5.0
    KEYCLOAK_JWKS_CACHE_TTL_SECONDS: float = 3600.0
    KEYCLOAK_JWKS_REFRESH_COOLDOWN_SECONDS: float = 30.0
    IDENTITY_JIT_ENABLED: bool = True
    SEED_USER_USERNAME: str = "atlas-admin"
    SEED_USER_PASSWORD: str | None = None
    SEED_USER_EMAIL: str = "atlas-admin@atlasrag.local"
    SEED_USER_DISPLAY_NAME: str = "Atlas Admin"
    SEED_USER_FIRST_NAME: str = "Atlas"
    SEED_USER_LAST_NAME: str = "Admin"

    MINIO_ENDPOINT_URL: str = "http://localhost:9000"
    MINIO_USE_SSL: bool = False
    MINIO_ROOT_USER: str = "atlas"
    MINIO_ROOT_PASSWORD: str = "atlas_dev_password"
    MINIO_BUCKET: str = "atlasrag"
    MINIO_REGION: str = "us-east-1"

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
