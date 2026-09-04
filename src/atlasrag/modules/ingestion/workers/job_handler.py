import asyncio
import uuid

from atlasrag.contracts.types.ingestion import ClaimedIngestionItem
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.workers.errors import (
    IngestionLeaseLost,
    PermanentIngestionError,
    TransientIngestionError,
)
from atlasrag.modules.ingestion.workers.heartbeat import LeaseHeartbeat
from atlasrag.modules.ingestion.workers.processor import IngestionProcessor

TRANSIENT_INGESTION_ERROR = "transient_ingestion_error"
UNEXPECTED_INGESTION_ERROR = "unexpected_ingestion_error"


class IngestionJobHandler:
    def __init__(
        self,
        *,
        lifecycle: IngestionLifecycleService,
        processor: IngestionProcessor,
        heartbeat: LeaseHeartbeat,
    ) -> None:
        self._lifecycle = lifecycle
        self._processor = processor
        self._heartbeat = heartbeat

    async def handle(self, *, ingestion_item_id: uuid.UUID) -> None:
        claim = await self._lifecycle.claim(item_id=ingestion_item_id)
        if claim is None:
            return

        try:
            await self._run_claimed_item(claim=claim)
        except IngestionLeaseLost:
            return
        except PermanentIngestionError as error:
            await self._lifecycle.mark_failed(
                item_id=claim.ingestion_item_id,
                attempt_number=claim.attempt_number,
                error_code=error.error_code,
                error_message=error.message,
            )
        except TransientIngestionError:
            await self._lifecycle.schedule_retry(
                item_id=claim.ingestion_item_id,
                attempt_number=claim.attempt_number,
                error_code=TRANSIENT_INGESTION_ERROR,
            )
        except Exception:
            # Unknown processor failures are retryable to avoid permanently losing work.
            # Do not persist arbitrary exception text because it can contain sensitive data.
            await self._lifecycle.schedule_retry(
                item_id=claim.ingestion_item_id,
                attempt_number=claim.attempt_number,
                error_code=UNEXPECTED_INGESTION_ERROR,
            )

    async def _run_claimed_item(self, *, claim: ClaimedIngestionItem) -> None:
        stop_heartbeat = asyncio.Event()
        lease_lost = asyncio.Event()
        processor_task = asyncio.create_task(self._processor.process(claim=claim))
        heartbeat_task = asyncio.create_task(
            self._heartbeat.run(
                item_id=claim.ingestion_item_id,
                attempt_number=claim.attempt_number,
                stop_event=stop_heartbeat,
                lease_lost_event=lease_lost,
            )
        )

        try:
            done, _ = await asyncio.wait(
                (processor_task, heartbeat_task),
                return_when=asyncio.FIRST_COMPLETED,
            )

            if heartbeat_task in done:
                heartbeat_error = self._task_error(heartbeat_task)
                if isinstance(heartbeat_error, IngestionLeaseLost):
                    raise heartbeat_error
                if heartbeat_error is None:
                    raise IngestionLeaseLost("Lease heartbeat stopped unexpectedly.")
                raise IngestionLeaseLost(
                    "Lease heartbeat terminated unexpectedly."
                ) from heartbeat_error

            processor_task.result()
            if lease_lost.is_set():
                raise IngestionLeaseLost("Ingestion lease was lost during processing.")
        finally:
            stop_heartbeat.set()
            for task in (processor_task, heartbeat_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(processor_task, heartbeat_task, return_exceptions=True)

    @staticmethod
    def _task_error(task: asyncio.Task[None]) -> BaseException | None:
        if task.cancelled():
            return asyncio.CancelledError()
        return task.exception()


__all__ = ["IngestionJobHandler"]
