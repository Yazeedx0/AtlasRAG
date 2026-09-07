import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from atlasrag.contracts.jobs import JobOutboxUnitOfWork
from atlasrag.contracts.types.jobs import ClaimedOutboxJob
from atlasrag.platform.jobs.backoff import ExponentialBackoff
from atlasrag.platform.jobs.config import TASK_BY_JOB_TYPE

UNKNOWN_JOB_TYPE_FAILURE_CODE = "unknown_job_type"
DISPATCH_ATTEMPTS_EXHAUSTED_FAILURE_CODE = "dispatch_attempts_exhausted"


class TaskDispatcher(Protocol):
    def publish(self, *, task_name: str, payload: dict[str, object]) -> None:
        ...


@dataclass(frozen=True, slots=True)
class OutboxPublishReport:
    claimed: int
    published: int
    dispatch_failures: int
    unknown_job_types: int
    dead_lettered: int
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
        max_attempts: int = 5,
        backoff: ExponentialBackoff | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._dispatcher = dispatcher
        self._lease_duration = lease_duration
        self._clock = clock
        self._max_attempts = max_attempts
        self._backoff = backoff or ExponentialBackoff(
            base=timedelta(seconds=5),
            maximum=timedelta(minutes=10),
        )

    async def publish_pending(self, *, limit: int) -> OutboxPublishReport:
        jobs = await self._claim(limit=limit)
        published = 0
        dispatch_failures = 0
        unknown_job_types = 0
        dead_lettered = 0
        unconfirmed_publications = 0
        unconfirmed_terminal_failures = 0

        for job in jobs:
            task_name = TASK_BY_JOB_TYPE.get(job.job_type)
            if task_name is None:
                marked_failed = await self._mark_failed(
                    job=job,
                    failure_code=UNKNOWN_JOB_TYPE_FAILURE_CODE,
                )
                unknown_job_types += 1
                dead_lettered += 1
                if not marked_failed:
                    unconfirmed_terminal_failures += 1
                continue

            try:
                await asyncio.to_thread(
                    self._dispatcher.publish,
                    task_name=task_name,
                    payload=job.payload,
                )
            except Exception as error:
                error_code = f"dispatch_failed:{type(error).__name__}"
                dispatch_failures += 1
                if job.attempt_number >= self._max_attempts:
                    dead_lettered += 1
                    if not await self._mark_failed(
                        job=job,
                        failure_code=DISPATCH_ATTEMPTS_EXHAUSTED_FAILURE_CODE,
                        last_error=error_code,
                    ):
                        unconfirmed_terminal_failures += 1
                else:
                    await self._release_claim(job=job, error_code=error_code)
                continue

            if await self._mark_published(job=job):
                published += 1
            else:
                unconfirmed_publications += 1

        return OutboxPublishReport(
            claimed=len(jobs),
            published=published,
            dispatch_failures=dispatch_failures,
            unknown_job_types=unknown_job_types,
            dead_lettered=dead_lettered,
            unconfirmed_publications=unconfirmed_publications,
            unconfirmed_terminal_failures=unconfirmed_terminal_failures,
        )

    async def _claim(self, *, limit: int) -> tuple[ClaimedOutboxJob, ...]:
        now = self._clock()
        async with self._uow_factory() as uow:
            jobs = await uow.outbox.claim_unpublished_batch(
                limit=limit,
                now=now,
                lease_expires_at=now + self._lease_duration,
            )
            if jobs:
                await uow.commit()
            return jobs

    async def _mark_published(self, *, job: ClaimedOutboxJob) -> bool:
        async with self._uow_factory() as uow:
            marked = await uow.outbox.mark_published(
                job_id=job.id,
                attempt_number=job.attempt_number,
                published_at=self._clock(),
            )
            if marked:
                await uow.commit()
            return marked

    async def _release_claim(self, *, job: ClaimedOutboxJob, error_code: str) -> bool:
        next_attempt_at = self._clock() + self._backoff.delay_for(
            attempt_number=job.attempt_number
        )
        async with self._uow_factory() as uow:
            released = await uow.outbox.release_publish_claim(
                job_id=job.id,
                attempt_number=job.attempt_number,
                error_code=error_code,
                next_attempt_at=next_attempt_at,
            )
            if released:
                await uow.commit()
            return released

    async def _mark_failed(
        self,
        *,
        job: ClaimedOutboxJob,
        failure_code: str,
        last_error: str | None = None,
    ) -> bool:
        async with self._uow_factory() as uow:
            marked = await uow.outbox.mark_failed(
                job_id=job.id,
                attempt_number=job.attempt_number,
                failed_at=self._clock(),
                failure_code=failure_code,
                last_error=last_error,
            )
            if marked:
                await uow.commit()
            return marked


__all__ = [
    "DISPATCH_ATTEMPTS_EXHAUSTED_FAILURE_CODE",
    "UNKNOWN_JOB_TYPE_FAILURE_CODE",
    "OutboxPublishReport",
    "OutboxPublisher",
    "TaskDispatcher",
]
