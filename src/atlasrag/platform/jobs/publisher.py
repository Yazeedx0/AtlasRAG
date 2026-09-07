import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from atlasrag.contracts.jobs import JobOutboxUnitOfWork
from atlasrag.contracts.types.jobs import ClaimedOutboxJob, JobType
from atlasrag.contracts.types.observability import JobStage, SpanName
from atlasrag.platform.jobs.config import TASK_BY_JOB_TYPE
from atlasrag.platform.observability import (
    annotate_span,
    record_outbox_attempt,
    record_outbox_backlog,
    record_outbox_failure,
    record_outbox_success,
    traced_stage,
)

_KNOWN_JOB_TYPES: frozenset[str] = frozenset(member.value for member in JobType)
UNKNOWN_JOB_TYPE_LABEL = "unknown"


def _job_type_label(job_type: str) -> str:
    return job_type if job_type in _KNOWN_JOB_TYPES else UNKNOWN_JOB_TYPE_LABEL

UNKNOWN_JOB_TYPE_FAILURE_CODE = "unknown_job_type"
DISPATCH_FAILED = "dispatch_failed"
UNCONFIRMED_PUBLICATION = "unconfirmed_publication"


class TaskDispatcher(Protocol):
    def publish(self, *, task_name: str, payload: dict[str, object]) -> None:
        ...


@dataclass(frozen=True, slots=True)
class OutboxPublishReport:
    claimed: int
    published: int
    dispatch_failures: int
    unknown_job_types: int
    unconfirmed_publications: int
    unconfirmed_terminal_failures: int


class OutboxPublisher:
    def __init__(
        self,
        uow_factory: Callable[[], JobOutboxUnitOfWork],
        dispatcher: TaskDispatcher,
        *,
        lease_duration: timedelta,
        clock: Callable[[], datetime],
    ) -> None:
        self._uow_factory = uow_factory
        self._dispatcher = dispatcher
        self._lease_duration = lease_duration
        self._clock = clock

    async def publish_pending(self, *, limit: int) -> OutboxPublishReport:
        jobs = await self._claim(limit=limit)
        published = 0
        dispatch_failures = 0
        unknown_job_types = 0
        unconfirmed_publications = 0
        unconfirmed_terminal_failures = 0

        for job in jobs:
            job_type = _job_type_label(job.job_type)
            record_outbox_attempt(job_type=job_type)
            task_name = TASK_BY_JOB_TYPE.get(job.job_type)
            if task_name is None:
                marked_failed = await self._mark_failed(
                    job=job,
                    failure_code=UNKNOWN_JOB_TYPE_FAILURE_CODE,
                )
                record_outbox_failure(
                    job_type=job_type,
                    error_code=UNKNOWN_JOB_TYPE_FAILURE_CODE,
                )
                unknown_job_types += 1
                if not marked_failed:
                    unconfirmed_terminal_failures += 1
                continue

            try:
                async with traced_stage(
                    SpanName.OUTBOX_PUBLISH,
                    stage=JobStage.OUTBOX_PUBLISH,
                    with_language=False,
                ):
                    await asyncio.to_thread(
                        self._dispatcher.publish,
                        task_name=task_name,
                        payload=job.payload,
                    )
            except Exception as error:
                await self._release_claim(
                    job=job,
                    error_code=f"dispatch_failed:{type(error).__name__}",
                )
                record_outbox_failure(job_type=job_type, error_code=DISPATCH_FAILED)
                dispatch_failures += 1
                continue

            if await self._mark_published(job=job):
                record_outbox_success(job_type=job_type)
                published += 1
            else:
                record_outbox_failure(job_type=job_type, error_code=UNCONFIRMED_PUBLICATION)
                unconfirmed_publications += 1

        return OutboxPublishReport(
            claimed=len(jobs),
            published=published,
            dispatch_failures=dispatch_failures,
            unknown_job_types=unknown_job_types,
            unconfirmed_publications=unconfirmed_publications,
            unconfirmed_terminal_failures=unconfirmed_terminal_failures,
        )

    async def record_backlog(self) -> dict[str, int]:
        async with self._uow_factory() as uow:
            pending = await uow.outbox.count_pending_by_job_type()
        backlog = {_job_type_label(job_type): count for job_type, count in pending.items()}
        for job_type in _KNOWN_JOB_TYPES:
            backlog.setdefault(job_type, 0)
        record_outbox_backlog(pending=backlog)
        return backlog

    async def _claim(self, *, limit: int) -> tuple[ClaimedOutboxJob, ...]:
        now = self._clock()
        async with traced_stage(
            SpanName.OUTBOX_CLAIM,
            stage=JobStage.OUTBOX_PUBLISH,
            with_language=False,
        ) as observation:
            async with self._uow_factory() as uow:
                jobs = await uow.outbox.claim_unpublished_batch(
                    limit=limit,
                    now=now,
                    lease_expires_at=now + self._lease_duration,
                )
                if jobs:
                    await uow.commit()
            annotate_span(observation.span, claimed_count=len(jobs))
            return jobs

    async def _mark_published(self, *, job: ClaimedOutboxJob) -> bool:
        async with traced_stage(
            SpanName.OUTBOX_MARK_PUBLISHED,
            stage=JobStage.OUTBOX_PUBLISH,
            with_language=False,
        ) as observation:
            async with self._uow_factory() as uow:
                marked = await uow.outbox.mark_published(
                    job_id=job.id,
                    attempt_number=job.attempt_number,
                    published_at=self._clock(),
                )
                if marked:
                    await uow.commit()
            annotate_span(observation.span, lease_retained=marked)
            return marked

    async def _release_claim(self, *, job: ClaimedOutboxJob, error_code: str) -> bool:
        async with self._uow_factory() as uow:
            released = await uow.outbox.release_publish_claim(
                job_id=job.id,
                attempt_number=job.attempt_number,
                error_code=error_code,
            )
            if released:
                await uow.commit()
            return released

    async def _mark_failed(
        self,
        *,
        job: ClaimedOutboxJob,
        failure_code: str,
    ) -> bool:
        async with self._uow_factory() as uow:
            marked = await uow.outbox.mark_failed(
                job_id=job.id,
                attempt_number=job.attempt_number,
                failed_at=self._clock(),
                failure_code=failure_code,
            )
            if marked:
                await uow.commit()
            return marked
