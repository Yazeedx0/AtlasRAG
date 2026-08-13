from enum import StrEnum
from functools import lru_cache
from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict



class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"

class Settings(BaseSettings):
    APP_NAME: str = "AtlasRAG"
    APP_VERSION: str = "1.0.0"

    ENVIROMENT: Environment = Environment.DEVELOPMENT

    DATABASE_URL: PostgresDsn
    DEBUG : bool = False
    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )





@lru_cache
def get_settings() -> Settings:
    return Settings()
