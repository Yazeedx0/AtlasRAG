from fastapi import FastAPI
from src import get_settings

from apps.api.router import api_router, register_exception_handlers
from atlasrag.bootstrap.lifespan import lifespan
from atlasrag.platform.observability import configure_observability

settings = get_settings()


def create_app() -> FastAPI:
    configure_observability(
        log_level=settings.LOG_LEVEL.value,
        json_logs=settings.LOG_JSON,
        tracing_enabled=settings.TRACING_ENABLED,
        metrics_enabled=settings.METRICS_ENABLED,
    )
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )
    register_exception_handlers(application)

    application.include_router(api_router)

    return application


app = create_app()
