from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from src.atlasrag.bootstrap.config import get_settings
from fastapi import FastAPI
from fastapi import status


settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
      
    )


    @application.get("/health", tags=["health"], status_code=status.HTTP_200_OK)
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()