from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from src.atlasrag.bootstrap.config import get_settings

from apps.api.router import api_router
from apps.api.routes import health

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

    # Probes stay unversioned so orchestrators and load balancers can point at a
    # stable /health across API versions.
    application.include_router(health.router)
    application.include_router(api_router)

    return application


app = create_app()
