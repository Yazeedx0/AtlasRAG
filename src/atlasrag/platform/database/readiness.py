import asyncio

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)

DEFAULT_DATABASE_READINESS_TIMEOUT_SECONDS = 2.0


class PostgresReadinessProbe:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        timeout_seconds: float = DEFAULT_DATABASE_READINESS_TIMEOUT_SECONDS,
    ) -> None:
        self._engine = engine
        self._timeout_seconds = timeout_seconds

    async def check(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._engine.connect() as connection:
                    result = await connection.execute(text("SELECT 1"))
        except (TimeoutError, SQLAlchemyError) as error:
            logger.warning(
                "database_readiness_check_failed",
                error_type=type(error).__name__,
            )
            return False

        return result.scalar_one() == 1


__all__ = ["PostgresReadinessProbe"]
