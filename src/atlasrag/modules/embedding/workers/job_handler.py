import asyncio
import uuid

from atlasrag.contracts.types.embedding import ClaimedEmbeddingRun
from atlasrag.modules.embedding.services.embedding_lifecycle import (
    EmbeddingLifecycleService,
)
from atlasrag.modules.embedding.workers.errors import (
    EmbeddingLeaseLost,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from atlasrag.modules.embedding.workers.heartbeat import EmbeddingLeaseHeartbeat
from atlasrag.modules.embedding.workers.processor import EmbeddingProcessor

TRANSIENT_EMBEDDING_ERROR = "transient_embedding_error"
UNEXPECTED_EMBEDDING_ERROR = "unexpected_embedding_error"


class EmbeddingJobHandler:
    def __init__(
        self,
        *,
        lifecycle: EmbeddingLifecycleService,
        processor: EmbeddingProcessor,
        heartbeat: EmbeddingLeaseHeartbeat,
    ) -> None:
        self._lifecycle = lifecycle
        self._processor = processor
        self._heartbeat = heartbeat

    async def handle(self, *, embedding_run_id: uuid.UUID) -> None:
        claim = await self._lifecycle.claim(run_id=embedding_run_id)
        if claim is None:
            return

        try:
            await self._run_claimed_run(claim=claim)
        except EmbeddingLeaseLost:
            return
        except PermanentEmbeddingError as error:
            await self._lifecycle.mark_failed(
                run_id=claim.embedding_run_id,
                attempt_number=claim.attempt_number,
                error_code=error.error_code,
                error_message=error.message,
            )
        except TransientEmbeddingError:
            await self._lifecycle.schedule_retry(
                run_id=claim.embedding_run_id,
                attempt_number=claim.attempt_number,
                error_code=TRANSIENT_EMBEDDING_ERROR,
            )
        except Exception:
            # Unknown processor failures are retryable to avoid permanently losing work.
            # Do not persist arbitrary exception text because it can contain sensitive data.
            await self._lifecycle.schedule_retry(
                run_id=claim.embedding_run_id,
                attempt_number=claim.attempt_number,
                error_code=UNEXPECTED_EMBEDDING_ERROR,
            )

    async def _run_claimed_run(self, *, claim: ClaimedEmbeddingRun) -> None:
        stop_heartbeat = asyncio.Event()
        lease_lost = asyncio.Event()
        processor_task = asyncio.create_task(self._processor.process(claim=claim))
        heartbeat_task = asyncio.create_task(
            self._heartbeat.run(
                run_id=claim.embedding_run_id,
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
                if isinstance(heartbeat_error, EmbeddingLeaseLost):
                    raise heartbeat_error
                if heartbeat_error is None:
                    raise EmbeddingLeaseLost("Lease heartbeat stopped unexpectedly.")
                raise EmbeddingLeaseLost(
                    "Lease heartbeat terminated unexpectedly."
                ) from heartbeat_error

            processor_task.result()
            if lease_lost.is_set():
                raise EmbeddingLeaseLost("Embedding lease was lost during processing.")
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


__all__ = [
    "TRANSIENT_EMBEDDING_ERROR",
    "UNEXPECTED_EMBEDDING_ERROR",
    "EmbeddingJobHandler",
]
