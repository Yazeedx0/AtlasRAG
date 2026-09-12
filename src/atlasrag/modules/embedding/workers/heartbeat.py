import asyncio
import uuid
from datetime import timedelta

from atlasrag.modules.embedding.services.embedding_lifecycle import (
    EmbeddingLifecycleService,
)
from atlasrag.modules.embedding.workers.errors import EmbeddingLeaseLost
from atlasrag.platform.jobs.heartbeat import LeasedJobHeartbeat


class EmbeddingLeaseHeartbeat:
    def __init__(
        self,
        lifecycle: EmbeddingLifecycleService,
        *,
        interval: timedelta,
    ) -> None:
        self._heartbeat = LeasedJobHeartbeat(
            lifecycle.heartbeat,
            interval=interval,
            lease_lost=EmbeddingLeaseLost,
            job_id_keyword="run_id",
        )

    async def run(
        self,
        *,
        run_id: uuid.UUID,
        attempt_number: int,
        stop_event: asyncio.Event,
        lease_lost_event: asyncio.Event,
    ) -> None:
        await self._heartbeat.run(
            job_id=run_id,
            attempt_number=attempt_number,
            stop_event=stop_event,
            lease_lost_event=lease_lost_event,
        )


__all__ = ["EmbeddingLeaseHeartbeat"]
