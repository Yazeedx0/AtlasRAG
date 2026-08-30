from fastapi import FastAPI

from apps.api.router import api_router
from atlasrag.bootstrap.lifespan import lifespan
from src import get_settings

settings = get_settings()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )

    application.include_router(api_router)

    return application


app = create_app()
