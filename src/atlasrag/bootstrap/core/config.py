from enum import Enum
from functools import lru_cache

from pydantic import AnyHttpUrl, Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

from atlasrag.contracts.types.ai_types import AiProvider


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

    GENERATION_PROVIDER: AiProvider = AiProvider.OPENAI
    GENERATION_MODEL: str = Field(default="gpt-4o-mini", min_length=1)
    EMBEDDING_PROVIDER: AiProvider = AiProvider.OPENAI
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-small", min_length=1)
    RERANK_PROVIDER: AiProvider = AiProvider.COHERE
    RERANK_MODEL: str = Field(default="rerank-v3.5", min_length=1)

    OPENAI_API_KEY: str | None = None
    OPENAI_TIMEOUT_SECONDS: float = 30.0
    OPENAI_MAX_RETRIES: int = 2
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_TIMEOUT_SECONDS: float = 30.0
    ANTHROPIC_MAX_RETRIES: int = 2
    COHERE_API_KEY: str | None = None
    COHERE_TIMEOUT_SECONDS: float = 30.0
    COHERE_MAX_RETRIES: int = 2
    GEMINI_API_KEY: str | None = None
    GEMINI_TIMEOUT_SECONDS: float = 30.0
    GEMINI_MAX_RETRIES: int = 2

    ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
        {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/html",
            "text/markdown",
            "text/plain",
        }
    )
    ACCEPTED_LANGUAGE_CODES: frozenset[str] = frozenset({"ar", "en"})
    ARTIFACT_KEY_MAX_LENGTH: int = Field(default=255, gt=0)
    LANGUAGE_CODE_MAX_LENGTH: int = Field(default=20, gt=0)
    MAX_FILE_SIZE_BYTES: int = Field(default=50 * 1024 * 1024, gt=0)
    STORAGE_PROVIDER: str = Field(default="s3", min_length=1)

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
