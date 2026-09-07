import asyncio
import uuid

import structlog

from atlasrag.contracts.types.ingestion import ClaimedIngestionItem
from atlasrag.contracts.types.jobs import JobType
from atlasrag.contracts.types.observability import (
    JobStage,
    LabelKey,
    MetricName,
    OutcomeLabel,
    SpanName,
)
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
from atlasrag.platform.observability import (
    StageObservation,
    annotate_span,
    failed_stage,
    ingestion_job_context,
    record_job_failed,
    record_job_started,
    record_lease_lost,
    record_retry,
    traced_stage,
    update_job_context,
)

TRANSIENT_INGESTION_ERROR = "transient_ingestion_error"
UNEXPECTED_INGESTION_ERROR = "unexpected_ingestion_error"

_JOB_TYPE = JobType.PROCESS_INGESTION_ITEM.value

logger = structlog.get_logger(__name__)


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
        with ingestion_job_context(
            job_type=_JOB_TYPE,
            ingestion_item_id=ingestion_item_id,
        ):
            async with traced_stage(
                SpanName.INGESTION_JOB,
                duration_metric=MetricName.INGESTION_DURATION_SECONDS,
                labels={LabelKey.JOB_TYPE: _JOB_TYPE},
            ) as job:
                await self._handle_in_context(
                    ingestion_item_id=ingestion_item_id,
                    job=job,
                )

    async def _handle_in_context(
        self,
        *,
        ingestion_item_id: uuid.UUID,
        job: StageObservation,
    ) -> None:
        async with traced_stage(SpanName.INGESTION_CLAIM, stage=JobStage.CLAIM) as claim_stage:
            claim = await self._lifecycle.claim(item_id=ingestion_item_id)
            annotate_span(claim_stage.span, claimed=claim is not None)

        if claim is None:
            job.set_status(OutcomeLabel.NOT_CLAIMED)
            annotate_span(job.span, claimed=False)
            logger.info("ingestion_job_not_claimed")
            return

        update_job_context(
            artifact_id=claim.document_artifact_id,
            attempt_number=claim.attempt_number,
        )
        annotate_span(job.span, claimed=True, attempt_number=claim.attempt_number)
        record_job_started(job_type=_JOB_TYPE)
        logger.info("ingestion_job_started")

        try:
            await self._run_claimed_item(claim=claim)
        except IngestionLeaseLost:
            job.set_status(OutcomeLabel.LEASE_LOST)
            record_lease_lost(job_type=_JOB_TYPE, stage=failed_stage())
            logger.warning("ingestion_lease_lost", stage=failed_stage().value)
            return
        except PermanentIngestionError as error:
            job.set_status(OutcomeLabel.FAILURE)
            record_job_failed(
                job_type=_JOB_TYPE,
                stage=failed_stage(),
                error_code=error.error_code,
            )
            logger.error(
                "ingestion_job_failed",
                error_code=error.error_code,
                stage=failed_stage().value,
            )
            await self._lifecycle.mark_failed(
                item_id=claim.ingestion_item_id,
                attempt_number=claim.attempt_number,
                error_code=error.error_code,
                error_message=error.message,
            )
        except TransientIngestionError:
            job.set_status(OutcomeLabel.RETRY)
            record_retry(
                job_type=_JOB_TYPE,
                stage=failed_stage(),
                error_code=TRANSIENT_INGESTION_ERROR,
            )
            logger.warning(
                "ingestion_job_retry_scheduled",
                error_code=TRANSIENT_INGESTION_ERROR,
                stage=failed_stage().value,
            )
            await self._lifecycle.schedule_retry(
                item_id=claim.ingestion_item_id,
                attempt_number=claim.attempt_number,
                error_code=TRANSIENT_INGESTION_ERROR,
            )
        except Exception as error:
            # Unknown processor failures are retryable to avoid permanently losing work.
            # Do not persist arbitrary exception text because it can contain sensitive data.
            job.set_status(OutcomeLabel.RETRY)
            record_retry(
                job_type=_JOB_TYPE,
                stage=failed_stage(),
                error_code=UNEXPECTED_INGESTION_ERROR,
            )
            logger.warning(
                "ingestion_job_retry_scheduled",
                error_code=UNEXPECTED_INGESTION_ERROR,
                error_type=type(error).__name__,
                stage=failed_stage().value,
            )
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
