import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from atlasrag.contracts.types.ingestion import (
    ClaimedIngestionItem,
    IngestionItemState,
    IngestionRunState,
    IngestionStatus,
)
from atlasrag.modules.ingestion.models import IngestionItem, IngestionRun

MAX_ATTEMPTS_EXCEEDED = "max_attempts_exceeded"


def _run_columns() -> tuple[object, ...]:
    return (
        IngestionRun.id,
        IngestionRun.configuration,
        IngestionRun.configuration_hash,
        IngestionRun.created_by_principal_id,
        IngestionRun.created_at,
    )


def _item_columns() -> tuple[object, ...]:
    return (
        IngestionItem.id,
        IngestionItem.ingestion_run_id,
        IngestionItem.document_artifact_id,
        IngestionItem.status,
        IngestionItem.attempt_count,
        IngestionItem.claimed_at,
        IngestionItem.lease_expires_at,
        IngestionItem.observed_file_hash,
        IngestionItem.execution_metadata,
        IngestionItem.error_code,
        IngestionItem.error_message,
        IngestionItem.started_at,
        IngestionItem.completed_at,
        IngestionItem.activated_at,
        IngestionItem.deactivated_at,
        IngestionItem.created_at,
    )


def _to_run_state(row: Row) -> IngestionRunState:
    return IngestionRunState(
        id=row.id,
        configuration=row.configuration,
        configuration_hash=row.configuration_hash,
        created_by_principal_id=row.created_by_principal_id,
        created_at=row.created_at,
    )


def _to_item_state(row: Row) -> IngestionItemState:
    return IngestionItemState(
        id=row.id,
        ingestion_run_id=row.ingestion_run_id,
        document_artifact_id=row.document_artifact_id,
        status=row.status,
        attempt_count=row.attempt_count,
        claimed_at=row.claimed_at,
        lease_expires_at=row.lease_expires_at,
        observed_file_hash=row.observed_file_hash,
        execution_metadata=row.execution_metadata,
        error_code=row.error_code,
        error_message=row.error_message,
        started_at=row.started_at,
        completed_at=row.completed_at,
        activated_at=row.activated_at,
        deactivated_at=row.deactivated_at,
        created_at=row.created_at,
    )


class IngestionRepository:
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
        configuration: dict[str, object],
        configuration_hash: str,
        created_by_principal_id: uuid.UUID | None,
    ) -> None:
        await self._session.execute(
            insert(IngestionRun).values(
                id=run_id,
                configuration=configuration,
                configuration_hash=configuration_hash,
                created_by_principal_id=created_by_principal_id,
            )
        )
        return None

    async def add_item(
        self,
        *,
        item_id: uuid.UUID,
        ingestion_run_id: uuid.UUID,
        document_artifact_id: uuid.UUID,
    ) -> None:
        await self._session.execute(
            insert(IngestionItem).values(
                id=item_id,
                ingestion_run_id=ingestion_run_id,
                document_artifact_id=document_artifact_id,
                status=IngestionStatus.PENDING,
            )
        )
        return None

    async def find_run(self, *, run_id: uuid.UUID) -> IngestionRunState | None:
        statement = select(*_run_columns()).where(IngestionRun.id == run_id)
        row = (await self._session.execute(statement)).one_or_none()
        return _to_run_state(row) if row is not None else None

    async def find_item(self, *, item_id: uuid.UUID) -> IngestionItemState | None:
        statement = select(*_item_columns()).where(IngestionItem.id == item_id)
        row = (await self._session.execute(statement)).one_or_none()
        return _to_item_state(row) if row is not None else None

    async def claim_item(
        self,
        *,
        item_id: uuid.UUID,
        now: datetime,
        lease_expires_at: datetime,
        max_attempts: int,
    ) -> ClaimedIngestionItem | None:
        statement = (
            update(IngestionItem)
            .where(
                IngestionItem.id == item_id,
                IngestionItem.attempt_count < max_attempts,
                or_(
                    IngestionItem.status == IngestionStatus.PENDING,
                    and_(
                        IngestionItem.status == IngestionStatus.RUNNING,
                        IngestionItem.lease_expires_at <= self._db_time_source(),
                    ),
                ),
            )
            .values(
                status=IngestionStatus.RUNNING,
                attempt_count=IngestionItem.attempt_count + 1,
                claimed_at=now,
                lease_expires_at=lease_expires_at,
                started_at=func.coalesce(IngestionItem.started_at, now),
            )
            .returning(
                IngestionItem.id,
                IngestionItem.document_artifact_id,
                IngestionItem.attempt_count,
                IngestionItem.claimed_at,
                IngestionItem.lease_expires_at,
            )
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None

        return ClaimedIngestionItem(
            ingestion_item_id=row.id,
            document_artifact_id=row.document_artifact_id,
            attempt_number=row.attempt_count,
            claimed_at=row.claimed_at,
            lease_expires_at=row.lease_expires_at,
        )

    async def heartbeat(
        self,
        *,
        item_id: uuid.UUID,
        attempt_number: int,
        lease_expires_at: datetime,
    ) -> int:
        statement = (
            update(IngestionItem)
            .where(
                *_owned_by(
                    item_id=item_id,
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
        item_id: uuid.UUID,
        attempt_number: int,
        error_code: str | None,
        error_message: str | None,
    ) -> int:
        statement = (
            update(IngestionItem)
            .where(
                *_owned_by(
                    item_id=item_id,
                    attempt_number=attempt_number,
                    db_time=self._db_time_source(),
                )
            )
            .values(
                status=IngestionStatus.PENDING,
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
        item_id: uuid.UUID,
        attempt_number: int,
        now: datetime,
        error_code: str,
        error_message: str | None,
        execution_metadata: dict[str, object] | None,
    ) -> int:
        values: dict[str, object] = {
            "status": IngestionStatus.FAILED,
            "completed_at": now,
            "claimed_at": None,
            "lease_expires_at": None,
            "error_code": error_code,
            "error_message": error_message,
        }
        if execution_metadata is not None:
            values["execution_metadata"] = execution_metadata

        statement = (
            update(IngestionItem)
            .where(
                *_owned_by(
                    item_id=item_id,
                    attempt_number=attempt_number,
                    db_time=self._db_time_source(),
                )
            )
            .values(**values)
        )
        result = await self._session.execute(statement)
        return result.rowcount

    async def find_expired_items(
        self,
        *,
        limit: int,
    ) -> tuple[IngestionItemState, ...]:
        statement = (
            select(*_item_columns())
            .where(
                IngestionItem.status == IngestionStatus.RUNNING,
                IngestionItem.lease_expires_at <= self._db_time_source(),
            )
            .order_by(IngestionItem.lease_expires_at)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(_to_item_state(row) for row in rows)

    async def fail_exhausted_expired_items(
        self,
        *,
        now: datetime,
        max_attempts: int,
    ) -> int:
        statement = (
            update(IngestionItem)
            .where(
                IngestionItem.status == IngestionStatus.RUNNING,
                IngestionItem.lease_expires_at <= self._db_time_source(),
                IngestionItem.attempt_count >= max_attempts,
            )
            .values(
                status=IngestionStatus.FAILED,
                completed_at=now,
                claimed_at=None,
                lease_expires_at=None,
                error_code=MAX_ATTEMPTS_EXCEEDED,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount


def _owned_by(
    *,
    item_id: uuid.UUID,
    attempt_number: int,
    db_time: ColumnElement[datetime],
) -> tuple[object, ...]:
    return (
        IngestionItem.id == item_id,
        IngestionItem.status == IngestionStatus.RUNNING,
        IngestionItem.attempt_count == attempt_number,
        IngestionItem.lease_expires_at > db_time,
    )
