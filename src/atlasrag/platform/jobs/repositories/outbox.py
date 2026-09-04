import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types.jobs import JobType
from atlasrag.platform.jobs.models import JobOutbox


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
