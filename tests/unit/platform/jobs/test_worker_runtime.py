import asyncio

import pytest

from atlasrag.platform.jobs.worker_runtime import WorkerAsyncRuntime

DATABASE_URL = "postgresql+asyncpg://unused:unused@localhost:5432/unused"


def make_runtime() -> WorkerAsyncRuntime:
    runtime = WorkerAsyncRuntime()
    runtime.initialize(database_url=DATABASE_URL, database_echo=False)
    return runtime


def test_runtime_is_not_usable_before_initialization() -> None:
    runtime = WorkerAsyncRuntime()

    assert runtime.initialized is False
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = runtime.session_factory


def test_initialize_is_idempotent() -> None:
    runtime = make_runtime()
    session_factory = runtime.session_factory

    runtime.initialize(database_url=DATABASE_URL, database_echo=True)

    assert runtime.session_factory is session_factory
    runtime.shutdown()


def test_run_executes_a_coroutine_on_the_runtime_loop() -> None:
    runtime = make_runtime()

    async def answer() -> int:
        return 42

    assert runtime.run(answer()) == 42
    runtime.shutdown()


def test_shutdown_releases_the_loop_and_allows_reinitialization() -> None:
    runtime = make_runtime()

    runtime.shutdown()

    assert runtime.initialized is False
    assert runtime.shutting_down is False

    runtime.initialize(database_url=DATABASE_URL, database_echo=False)
    assert runtime.initialized is True
    runtime.shutdown()


def test_shutdown_without_initialization_is_a_noop() -> None:
    runtime = WorkerAsyncRuntime()

    runtime.shutdown()

    assert runtime.initialized is False


def test_shutdown_drains_pending_work_before_closing_the_loop() -> None:
    runtime = make_runtime()
    finished = asyncio.Event()

    async def background() -> None:
        await asyncio.sleep(0.05)
        finished.set()

    async def schedule() -> asyncio.Task[None]:
        return asyncio.create_task(background())

    task = runtime.run(schedule())

    runtime.shutdown(grace_seconds=5.0)

    assert task.done()
    assert task.cancelled() is False
    assert finished.is_set()


def test_shutdown_cancels_work_that_outlives_the_grace_period() -> None:
    runtime = make_runtime()

    async def never_finishes() -> None:
        await asyncio.sleep(3600)

    async def schedule() -> asyncio.Task[None]:
        return asyncio.create_task(never_finishes())

    task = runtime.run(schedule())

    runtime.shutdown(grace_seconds=0.05)

    assert task.cancelled()
    assert runtime.initialized is False
