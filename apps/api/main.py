from fastapi import FastAPI

from apps.api.router import api_router
from apps.api.routes import health
from atlasrag.bootstrap.lifespan import lifespan
from src import get_settings

settings = get_settings()


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
