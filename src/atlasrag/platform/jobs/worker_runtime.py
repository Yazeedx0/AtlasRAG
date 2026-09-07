import asyncio
from collections.abc import Coroutine
from typing import TypeVar

import structlog
from celery import current_app
from celery.signals import (
    worker_process_init,
    worker_process_shutdown,
    worker_shutdown,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = structlog.get_logger(__name__)

Result = TypeVar("Result")

DEFAULT_SHUTDOWN_GRACE_SECONDS = 10.0


class WorkerAsyncRuntime:
    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._shutting_down = False

    @property
    def initialized(self) -> bool:
        return self._event_loop is not None

    @property
    def shutting_down(self) -> bool:
        return self._shutting_down

    def initialize(self, *, database_url: str, database_echo: bool) -> None:
        if self._event_loop is not None:
            return

        self._shutting_down = False
        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)
        self._engine = create_async_engine(
            database_url,
            echo=database_echo,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("Worker async runtime is not initialized")
        return self._session_factory

    def run(self, coroutine: Coroutine[object, object, Result]) -> Result:
        event_loop = self._event_loop
        if event_loop is None:
            coroutine.close()
            raise RuntimeError("Worker async runtime is not initialized")
        if self._shutting_down:
            coroutine.close()
            raise RuntimeError("Worker async runtime is shutting down")
        return event_loop.run_until_complete(coroutine)

    def shutdown(
        self,
        *,
        grace_seconds: float = DEFAULT_SHUTDOWN_GRACE_SECONDS,
    ) -> None:
        event_loop = self._event_loop
        engine = self._engine
        if event_loop is None:
            return

        self._shutting_down = True
        try:
            self._drain(event_loop, grace_seconds=grace_seconds)
            if engine is not None:
                event_loop.run_until_complete(engine.dispose())
            event_loop.run_until_complete(event_loop.shutdown_asyncgens())
        finally:
            event_loop.close()
            self._engine = None
            self._event_loop = None
            self._session_factory = None
            self._shutting_down = False

    @staticmethod
    def _drain(
        event_loop: asyncio.AbstractEventLoop,
        *,
        grace_seconds: float,
    ) -> None:
        pending = [task for task in asyncio.all_tasks(event_loop) if not task.done()]
        if not pending:
            return

        logger.info("worker_runtime_draining_tasks", pending=len(pending))
        event_loop.run_until_complete(
            _await_pending(pending, grace_seconds=grace_seconds)
        )


async def _await_pending(
    pending: list[asyncio.Task[object]],
    *,
    grace_seconds: float,
) -> None:
    try:
        async with asyncio.timeout(grace_seconds):
            await asyncio.gather(*pending, return_exceptions=True)
    except TimeoutError:
        logger.warning("worker_runtime_drain_timed_out", pending=len(pending))
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


_runtime = WorkerAsyncRuntime()


def get_worker_async_runtime() -> WorkerAsyncRuntime:
    return _runtime


@worker_process_init.connect
def initialize_worker_async_runtime(**_: object) -> None:
    configuration = current_app.conf
    database_url = configuration.get("atlas_database_url")
    if database_url is None:
        return

    _runtime.initialize(
        database_url=database_url,
        database_echo=configuration.get("atlas_database_echo", False),
    )
    logger.info("worker_runtime_initialized")


@worker_process_shutdown.connect
def shutdown_worker_async_runtime(**_: object) -> None:
    _runtime.shutdown()
    logger.info("worker_runtime_shutdown")


@worker_shutdown.connect
def shutdown_worker_async_runtime_on_worker_stop(**_: object) -> None:
    _runtime.shutdown()


__all__ = [
    "DEFAULT_SHUTDOWN_GRACE_SECONDS",
    "WorkerAsyncRuntime",
    "get_worker_async_runtime",
]
