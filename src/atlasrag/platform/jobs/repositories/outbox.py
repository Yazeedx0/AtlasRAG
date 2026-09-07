import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from atlasrag.contracts.types.jobs import ClaimedOutboxJob, DeadLetteredJob, JobType
from atlasrag.platform.jobs.models import JobOutbox


def _dead_letter_columns() -> tuple[object, ...]:
    return (
        JobOutbox.id,
        JobOutbox.job_type,
        JobOutbox.aggregate_id,
        JobOutbox.attempt_count,
        JobOutbox.failed_at,
        JobOutbox.failure_code,
        JobOutbox.last_error,
    )


class OutboxRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        db_time: Callable[[], ColumnElement[datetime]] | None = None,
    ) -> None:
        self._session = session
        self._db_time_source = db_time or func.now

    async def enqueue(
        self,
        *,
        job_id: uuid.UUID,
        job_type: JobType,
        aggregate_id: uuid.UUID,
        payload: dict[str, object],
    ) -> None:
        await self._session.execute(
            insert(JobOutbox).values(
                id=job_id,
                job_type=job_type.value,
                aggregate_id=aggregate_id,
                payload=payload,
            )
        )

    async def discard_pending_for_aggregate(
        self,
        *,
        job_type: JobType,
        aggregate_id: uuid.UUID,
        failed_at: datetime,
        failure_code: str,
    ) -> int:
        statement = (
            update(JobOutbox)
            .where(
                JobOutbox.job_type == job_type.value,
                JobOutbox.aggregate_id == aggregate_id,
                JobOutbox.published_at.is_(None),
                JobOutbox.failed_at.is_(None),
            )
            .values(
                failed_at=failed_at,
                failure_code=failure_code,
                claimed_at=None,
                lease_expires_at=None,
                next_attempt_at=None,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount

    async def claim_unpublished_batch(
        self,
        *,
        limit: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> tuple[ClaimedOutboxJob, ...]:
        candidate_ids = (
            select(JobOutbox.id)
            .where(
                JobOutbox.published_at.is_(None),
                JobOutbox.failed_at.is_(None),
                or_(
                    JobOutbox.lease_expires_at.is_(None),
                    JobOutbox.lease_expires_at <= self._db_time_source(),
                ),
                or_(
                    JobOutbox.next_attempt_at.is_(None),
                    JobOutbox.next_attempt_at <= self._db_time_source(),
                ),
            )
            .order_by(JobOutbox.created_at, JobOutbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .cte("claimable_job_outbox")
        )
        statement = (
            update(JobOutbox)
            .where(JobOutbox.id.in_(select(candidate_ids.c.id)))
            .values(
                attempt_count=JobOutbox.attempt_count + 1,
                claimed_at=now,
                lease_expires_at=lease_expires_at,
                next_attempt_at=None,
            )
            .returning(
                JobOutbox.id,
                JobOutbox.job_type,
                JobOutbox.aggregate_id,
                JobOutbox.payload,
                JobOutbox.attempt_count,
                JobOutbox.lease_expires_at,
            )
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(
            ClaimedOutboxJob(
                id=row.id,
                job_type=row.job_type,
                aggregate_id=row.aggregate_id,
                payload=row.payload,
                attempt_number=row.attempt_count,
                lease_expires_at=row.lease_expires_at,
            )
            for row in rows
        )

    async def mark_published(
        self,
        *,
        job_id: uuid.UUID,
        attempt_number: int,
        published_at: datetime,
    ) -> bool:
        statement = (
            update(JobOutbox)
            .where(*self._owned_by(job_id=job_id, attempt_number=attempt_number))
            .values(
                published_at=published_at,
                claimed_at=None,
                lease_expires_at=None,
                next_attempt_at=None,
                last_error=None,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount == 1

    async def mark_failed(
        self,
        *,
        job_id: uuid.UUID,
        attempt_number: int,
        failed_at: datetime,
        failure_code: str,
        last_error: str | None = None,
    ) -> bool:
        statement = (
            update(JobOutbox)
            .where(*self._owned_by(job_id=job_id, attempt_number=attempt_number))
            .values(
                failed_at=failed_at,
                failure_code=failure_code,
                claimed_at=None,
                lease_expires_at=None,
                next_attempt_at=None,
                last_error=last_error,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount == 1

    async def release_publish_claim(
        self,
        *,
        job_id: uuid.UUID,
        attempt_number: int,
        error_code: str,
        next_attempt_at: datetime,
    ) -> bool:
        statement = (
            update(JobOutbox)
            .where(*self._owned_by(job_id=job_id, attempt_number=attempt_number))
            .values(
                claimed_at=None,
                lease_expires_at=None,
                next_attempt_at=next_attempt_at,
                last_error=error_code,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount == 1

    async def count_pending(self) -> int:
        statement = (
            select(func.count())
            .select_from(JobOutbox)
            .where(
                JobOutbox.published_at.is_(None),
                JobOutbox.failed_at.is_(None),
            )
        )
        return (await self._session.execute(statement)).scalar_one()

    async def count_dead_lettered(self) -> int:
        statement = (
            select(func.count())
            .select_from(JobOutbox)
            .where(JobOutbox.failed_at.is_not(None))
        )
        return (await self._session.execute(statement)).scalar_one()

    async def find_dead_lettered(self, *, limit: int) -> tuple[DeadLetteredJob, ...]:
        statement = (
            select(*_dead_letter_columns())
            .where(JobOutbox.failed_at.is_not(None))
            .order_by(JobOutbox.failed_at.desc(), JobOutbox.id)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(
            DeadLetteredJob(
                id=row.id,
                job_type=row.job_type,
                aggregate_id=row.aggregate_id,
                attempt_count=row.attempt_count,
                failed_at=row.failed_at,
                failure_code=row.failure_code,
                last_error=row.last_error,
            )
            for row in rows
        )

    def _owned_by(
        self,
        *,
        job_id: uuid.UUID,
        attempt_number: int,
    ) -> tuple[object, ...]:
        return (
            JobOutbox.id == job_id,
            JobOutbox.published_at.is_(None),
            JobOutbox.failed_at.is_(None),
            JobOutbox.attempt_count == attempt_number,
            JobOutbox.lease_expires_at > self._db_time_source(),
        )


__all__ = ["OutboxRepository"]
