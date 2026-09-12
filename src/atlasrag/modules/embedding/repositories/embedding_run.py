import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from atlasrag.contracts.types.embedding import (
    ClaimedEmbeddingRun,
    EmbeddingRunState,
    EmbeddingStatus,
)
from atlasrag.modules.embedding.models import EmbeddingRun

MAX_ATTEMPTS_EXCEEDED = "max_attempts_exceeded"

_IN_FLIGHT_STATUSES = (EmbeddingStatus.PENDING, EmbeddingStatus.RUNNING)


def _run_columns() -> tuple[object, ...]:
    return (
        EmbeddingRun.id,
        EmbeddingRun.ingestion_item_id,
        EmbeddingRun.embedding_model_id,
        EmbeddingRun.configuration,
        EmbeddingRun.configuration_hash,
        EmbeddingRun.status,
        EmbeddingRun.attempt_count,
        EmbeddingRun.claimed_at,
        EmbeddingRun.lease_expires_at,
        EmbeddingRun.error_code,
        EmbeddingRun.error_message,
        EmbeddingRun.execution_metadata,
        EmbeddingRun.created_by_principal_id,
        EmbeddingRun.started_at,
        EmbeddingRun.completed_at,
        EmbeddingRun.created_at,
    )


def _to_run_state(row: Row) -> EmbeddingRunState:
    return EmbeddingRunState(
        id=row.id,
        ingestion_item_id=row.ingestion_item_id,
        embedding_model_id=row.embedding_model_id,
        configuration=row.configuration,
        configuration_hash=row.configuration_hash,
        status=row.status,
        attempt_count=row.attempt_count,
        claimed_at=row.claimed_at,
        lease_expires_at=row.lease_expires_at,
        error_code=row.error_code,
        error_message=row.error_message,
        execution_metadata=row.execution_metadata,
        created_by_principal_id=row.created_by_principal_id,
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )


def _owned_by(
    *,
    run_id: uuid.UUID,
    attempt_number: int,
    db_time: ColumnElement[datetime],
) -> tuple[object, ...]:
    return (
        EmbeddingRun.id == run_id,
        EmbeddingRun.status == EmbeddingStatus.RUNNING,
        EmbeddingRun.attempt_count == attempt_number,
        EmbeddingRun.lease_expires_at > db_time,
    )


class EmbeddingRunRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        db_time: Callable[[], ColumnElement[datetime]] | None = None,
    ) -> None:
        self._session = session
        self._db_time_source = db_time or func.now

    async def add_run(
        self,
        *,
        run_id: uuid.UUID,
        ingestion_item_id: uuid.UUID,
        embedding_model_id: uuid.UUID,
        configuration: dict[str, object],
        configuration_hash: str,
        created_by_principal_id: uuid.UUID | None,
    ) -> None:
        await self._session.execute(
            insert(EmbeddingRun).values(
                id=run_id,
                ingestion_item_id=ingestion_item_id,
                embedding_model_id=embedding_model_id,
                configuration=configuration,
                configuration_hash=configuration_hash,
                created_by_principal_id=created_by_principal_id,
                status=EmbeddingStatus.PENDING,
            )
        )
        return None

    async def find_run(self, *, run_id: uuid.UUID) -> EmbeddingRunState | None:
        statement = select(*_run_columns()).where(EmbeddingRun.id == run_id)
        row = (await self._session.execute(statement)).one_or_none()
        return _to_run_state(row) if row is not None else None

    async def find_in_flight_run(
        self,
        *,
        ingestion_item_id: uuid.UUID,
        embedding_model_id: uuid.UUID,
    ) -> EmbeddingRunState | None:
        statement = select(*_run_columns()).where(
            EmbeddingRun.ingestion_item_id == ingestion_item_id,
            EmbeddingRun.embedding_model_id == embedding_model_id,
            EmbeddingRun.status.in_(_IN_FLIGHT_STATUSES),
        )
        row = (await self._session.execute(statement)).one_or_none()
        return _to_run_state(row) if row is not None else None

    async def claim_run(
        self,
        *,
        run_id: uuid.UUID,
        now: datetime,
        lease_expires_at: datetime,
        max_attempts: int,
    ) -> ClaimedEmbeddingRun | None:
        statement = (
            update(EmbeddingRun)
            .where(
                EmbeddingRun.id == run_id,
                EmbeddingRun.attempt_count < max_attempts,
                or_(
                    EmbeddingRun.status == EmbeddingStatus.PENDING,
                    and_(
                        EmbeddingRun.status == EmbeddingStatus.RUNNING,
                        EmbeddingRun.lease_expires_at <= self._db_time_source(),
                    ),
                ),
            )
            .values(
                status=EmbeddingStatus.RUNNING,
                attempt_count=EmbeddingRun.attempt_count + 1,
                claimed_at=now,
                lease_expires_at=lease_expires_at,
                started_at=func.coalesce(EmbeddingRun.started_at, now),
            )
            .returning(
                EmbeddingRun.id,
                EmbeddingRun.ingestion_item_id,
                EmbeddingRun.embedding_model_id,
                EmbeddingRun.attempt_count,
                EmbeddingRun.claimed_at,
                EmbeddingRun.lease_expires_at,
            )
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None

        return ClaimedEmbeddingRun(
            embedding_run_id=row.id,
            ingestion_item_id=row.ingestion_item_id,
            embedding_model_id=row.embedding_model_id,
            attempt_number=row.attempt_count,
            claimed_at=row.claimed_at,
            lease_expires_at=row.lease_expires_at,
        )

    async def heartbeat(
        self,
        *,
        run_id: uuid.UUID,
        attempt_number: int,
        lease_expires_at: datetime,
    ) -> int:
        statement = (
            update(EmbeddingRun)
            .where(
                *_owned_by(
                    run_id=run_id,
                    attempt_number=attempt_number,
                    db_time=self._db_time_source(),
                )
            )
            .values(lease_expires_at=lease_expires_at)
        )
        result = await self._session.execute(statement)
        return result.rowcount

    async def release_for_retry(
        self,
        *,
        run_id: uuid.UUID,
        attempt_number: int,
        error_code: str | None,
        error_message: str | None,
    ) -> int:
        statement = (
            update(EmbeddingRun)
            .where(
                *_owned_by(
                    run_id=run_id,
                    attempt_number=attempt_number,
                    db_time=self._db_time_source(),
                )
            )
            .values(
                status=EmbeddingStatus.PENDING,
                claimed_at=None,
                lease_expires_at=None,
                error_code=error_code,
                error_message=error_message,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount

    async def mark_failed(
        self,
        *,
        run_id: uuid.UUID,
        attempt_number: int,
        now: datetime,
        error_code: str,
        error_message: str | None,
        execution_metadata: dict[str, object] | None,
    ) -> int:
        values: dict[str, object] = {
            "status": EmbeddingStatus.FAILED,
            "completed_at": now,
            "claimed_at": None,
            "lease_expires_at": None,
            "error_code": error_code,
            "error_message": error_message,
        }
        if execution_metadata is not None:
            values["execution_metadata"] = execution_metadata

        statement = (
            update(EmbeddingRun)
            .where(
                *_owned_by(
                    run_id=run_id,
                    attempt_number=attempt_number,
                    db_time=self._db_time_source(),
                )
            )
            .values(**values)
        )
        result = await self._session.execute(statement)
        return result.rowcount

    async def mark_completed(
        self,
        *,
        run_id: uuid.UUID,
        attempt_number: int,
        now: datetime,
        execution_metadata: dict[str, object],
    ) -> int:
        statement = (
            update(EmbeddingRun)
            .where(
                *_owned_by(
                    run_id=run_id,
                    attempt_number=attempt_number,
                    db_time=self._db_time_source(),
                )
            )
            .values(
                status=EmbeddingStatus.COMPLETED,
                completed_at=now,
                claimed_at=None,
                lease_expires_at=None,
                execution_metadata=execution_metadata,
                error_code=None,
                error_message=None,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount

    async def find_expired_runs(self, *, limit: int) -> tuple[EmbeddingRunState, ...]:
        statement = (
            select(*_run_columns())
            .where(
                EmbeddingRun.status == EmbeddingStatus.RUNNING,
                EmbeddingRun.lease_expires_at <= self._db_time_source(),
            )
            .order_by(EmbeddingRun.lease_expires_at)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(_to_run_state(row) for row in rows)

    async def fail_exhausted_expired_runs(
        self,
        *,
        now: datetime,
        max_attempts: int,
    ) -> int:
        statement = (
            update(EmbeddingRun)
            .where(
                EmbeddingRun.status == EmbeddingStatus.RUNNING,
                EmbeddingRun.lease_expires_at <= self._db_time_source(),
                EmbeddingRun.attempt_count >= max_attempts,
            )
            .values(
                status=EmbeddingStatus.FAILED,
                completed_at=now,
                claimed_at=None,
                lease_expires_at=None,
                error_code=MAX_ATTEMPTS_EXCEEDED,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount


__all__ = ["MAX_ATTEMPTS_EXCEEDED", "EmbeddingRunRepository"]
