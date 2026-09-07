import asyncio
from collections.abc import Coroutine
from typing import TypeVar

from celery.signals import worker_process_shutdown
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

Result = TypeVar("Result")


class WorkerAsyncRuntime:
    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def initialize(self, *, database_url: str, database_echo: bool) -> None:
        if self._event_loop is not None:
            return

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
            raise RuntimeError("Worker async runtime is not initialized")
        return event_loop.run_until_complete(coroutine)

    def shutdown(self) -> None:
        event_loop = self._event_loop
        engine = self._engine
        if event_loop is None:
            return

        try:
            if engine is not None:
                event_loop.run_until_complete(engine.dispose())
        finally:
            event_loop.close()
            self._engine = None
            self._event_loop = None
            self._session_factory = None


_runtime = WorkerAsyncRuntime()


def get_worker_async_runtime() -> WorkerAsyncRuntime:
    return _runtime


@worker_process_shutdown.connect
def shutdown_worker_async_runtime(**_: object) -> None:
    _runtime.shutdown()
