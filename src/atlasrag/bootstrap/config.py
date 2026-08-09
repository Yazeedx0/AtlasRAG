from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "AtlasRAG"
    APP_VERSION: str = "1.0.0"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"



def get_settings() -> Settings:
    return Settings()