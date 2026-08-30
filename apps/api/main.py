from fastapi import FastAPI

from apps.api.router import api_router, register_exception_handlers
from atlasrag.bootstrap.lifespan import lifespan
from src import get_settings

settings = get_settings()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )
    register_exception_handlers(application)

    application.include_router(api_router)

    return application


app = create_app()
