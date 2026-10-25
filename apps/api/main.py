from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src import get_settings

from apps.api.router import api_router, register_exception_handlers
from atlasrag.bootstrap.lifespan import lifespan

settings = get_settings()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.FRONTEND_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_exception_handlers(application)

    application.include_router(api_router)

    return application


app = create_app()
