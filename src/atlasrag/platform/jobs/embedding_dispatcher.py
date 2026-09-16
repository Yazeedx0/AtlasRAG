import asyncio
from uuid import UUID

from celery import Celery

from atlasrag.platform.jobs.constants import PROCESS_EMBEDDING_TASK


class CeleryEmbeddingRunDispatcher:
    """Sends a tiny, best-effort notification after the run transaction commits."""

    def __init__(self, celery_app: Celery) -> None:
        self._celery_app = celery_app

    async def dispatch_embedding_run(self, *, embedding_run_id: UUID) -> None:
        await asyncio.to_thread(
            self._celery_app.send_task,
            PROCESS_EMBEDDING_TASK,
            kwargs={"embedding_run_id": str(embedding_run_id)},
        )


__all__ = ["CeleryEmbeddingRunDispatcher"]
