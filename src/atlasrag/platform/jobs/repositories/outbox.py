import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from atlasrag.contracts.types.jobs import ClaimedOutboxJob, JobType
from atlasrag.platform.jobs.models import JobOutbox


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
                or_(
                    JobOutbox.lease_expires_at.is_(None),
                    JobOutbox.lease_expires_at <= self._db_time_source(),
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
                last_error=None,
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
    ) -> bool:
        statement = (
            update(JobOutbox)
            .where(*self._owned_by(job_id=job_id, attempt_number=attempt_number))
            .values(
                claimed_at=None,
                lease_expires_at=None,
                last_error=error_code,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount == 1

    def _owned_by(
        self,
        *,
        job_id: uuid.UUID,
        attempt_number: int,
    ) -> tuple[object, ...]:
        return (
            JobOutbox.id == job_id,
            JobOutbox.published_at.is_(None),
            JobOutbox.attempt_count == attempt_number,
            JobOutbox.lease_expires_at > self._db_time_source(),
        )
