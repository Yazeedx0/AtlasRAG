from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src import get_settings


def create_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        str(settings.DATABASE_URL),
        echo=settings.DATABASE_ECHO,
        pool_pre_ping=True,
    )


@lru_cache
def get_engine() -> AsyncEngine:
    return create_engine()
