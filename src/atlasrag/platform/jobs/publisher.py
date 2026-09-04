import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from atlasrag.contracts.jobs import JobOutboxUnitOfWork
from atlasrag.contracts.types.jobs import ClaimedOutboxJob
from atlasrag.platform.jobs.config import TASK_BY_JOB_TYPE


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

        for job in jobs:
            task_name = TASK_BY_JOB_TYPE.get(job.job_type)
            if task_name is None:
                await self._release_claim(job=job, error_code="unknown_job_type")
                unknown_job_types += 1
                continue

            try:
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
                dispatch_failures += 1
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
            unconfirmed_publications=unconfirmed_publications,
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
        async with self._uow_factory() as uow:
            released = await uow.outbox.release_publish_claim(
                job_id=job.id,
                attempt_number=job.attempt_number,
                error_code=error_code,
            )
            if released:
                await uow.commit()
            return released
