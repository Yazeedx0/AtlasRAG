import asyncio
import uuid
from datetime import timedelta

from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.workers.errors import (
    IngestionLeaseLost,
)


class LeaseHeartbeat:
    def __init__(
        self,
        lifecycle: IngestionLifecycleService,
        *,
        interval: timedelta,
    ) -> None:
        if interval.total_seconds() <= 0:
            raise ValueError("Heartbeat interval must be positive")

        self._lifecycle = lifecycle
        self._interval = interval

    async def run(
        self,
        *,
        item_id: uuid.UUID,
        attempt_number: int,
        stop_event: asyncio.Event,
        lease_lost_event: asyncio.Event,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._interval.total_seconds(),
                )
                return
            except TimeoutError:
                pass

            try:
                renewed = await self._lifecycle.heartbeat(
                    item_id=item_id,
                    attempt_number=attempt_number,
                )
            except Exception as error:
                lease_lost_event.set()
                raise IngestionLeaseLost(
                    "Unable to renew the ingestion lease."
                ) from error

            if not renewed:
                lease_lost_event.set()
                raise IngestionLeaseLost(
                    "Ingestion lease is no longer owned by this worker."
                )


__all__ = ["LeaseHeartbeat"]
