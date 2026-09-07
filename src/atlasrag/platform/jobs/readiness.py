import asyncio

import structlog
from celery import Celery

logger = structlog.get_logger(__name__)

DEFAULT_BROKER_READINESS_TIMEOUT_SECONDS = 2.0
DEFAULT_WORKER_PING_TIMEOUT_SECONDS = 2.0


class CeleryBrokerReadinessProbe:
    def __init__(
        self,
        celery_app: Celery,
        *,
        timeout_seconds: float = DEFAULT_BROKER_READINESS_TIMEOUT_SECONDS,
    ) -> None:
        self._celery_app = celery_app
        self._timeout_seconds = timeout_seconds

    async def check(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await asyncio.to_thread(self._ensure_connection)
        except (TimeoutError, OSError) as error:
            logger.warning(
                "broker_readiness_check_failed",
                error_type=type(error).__name__,
            )
            return False

    def _ensure_connection(self) -> bool:
        connection = self._celery_app.connection_for_write()
        try:
            connection.ensure_connection(max_retries=0, timeout=self._timeout_seconds)
        except Exception as error:
            logger.warning(
                "broker_connection_unavailable",
                error_type=type(error).__name__,
            )
            return False
        finally:
            connection.release()
        return True


class CeleryWorkerReadinessProbe:
    def __init__(
        self,
        celery_app: Celery,
        *,
        timeout_seconds: float = DEFAULT_WORKER_PING_TIMEOUT_SECONDS,
    ) -> None:
        self._celery_app = celery_app
        self._timeout_seconds = timeout_seconds

    async def check(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout_seconds + 1.0):
                replies = await asyncio.to_thread(self._ping)
        except TimeoutError:
            logger.warning("worker_readiness_check_timed_out")
            return False

        return bool(replies)

    def _ping(self) -> list[dict[str, object]]:
        try:
            return self._celery_app.control.ping(timeout=self._timeout_seconds) or []
        except Exception as error:
            logger.warning(
                "worker_ping_failed",
                error_type=type(error).__name__,
            )
            return []


__all__ = [
    "DEFAULT_BROKER_READINESS_TIMEOUT_SECONDS",
    "DEFAULT_WORKER_PING_TIMEOUT_SECONDS",
    "CeleryBrokerReadinessProbe",
    "CeleryWorkerReadinessProbe",
]
