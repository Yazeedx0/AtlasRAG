from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from atlasrag.contracts.embedding import EmbeddingRunDispatcher, EmbeddingUnitOfWork
from atlasrag.contracts.types.embedding import EmbeddingRunState

from .embedding_lifecycle import EmbeddingLifecycleService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingRecoveryReport:
    redispatched_pending: int
    redispatched_expired: int
    failed_exhausted: int
    dispatch_failures: int


class EmbeddingRecoveryService:
    """Redelivers disposable Celery notifications from durable run state."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], EmbeddingUnitOfWork],
        lifecycle: EmbeddingLifecycleService,
        dispatcher: EmbeddingRunDispatcher,
        pending_age: timedelta,
        batch_size: int,
        clock: Callable[[], datetime],
    ) -> None:
        if pending_age <= timedelta():
            raise ValueError("pending_age must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._uow_factory = uow_factory
        self._lifecycle = lifecycle
        self._dispatcher = dispatcher
        self._pending_age = pending_age
        self._batch_size = batch_size
        self._clock = clock

    async def recover(self) -> EmbeddingRecoveryReport:
        failed_exhausted = await self._lifecycle.reap_expired_runs()
        pending = await self._stale_pending_runs()
        expired = await self._expired_runs()
        pending_sent, pending_failures = await self._dispatch(runs=pending, source="pending")
        expired_sent, expired_failures = await self._dispatch(runs=expired, source="expired")
        return EmbeddingRecoveryReport(
            redispatched_pending=pending_sent,
            redispatched_expired=expired_sent,
            failed_exhausted=failed_exhausted,
            dispatch_failures=pending_failures + expired_failures,
        )

    async def _stale_pending_runs(self) -> tuple[EmbeddingRunState, ...]:
        async with self._uow_factory() as uow:
            return await uow.runs.find_stale_pending_runs(
                pending_before=self._clock() - self._pending_age,
                limit=self._batch_size,
            )

    async def _expired_runs(self) -> tuple[EmbeddingRunState, ...]:
        async with self._uow_factory() as uow:
            return await uow.runs.find_expired_runs(limit=self._batch_size)

    async def _dispatch(
        self,
        *,
        runs: tuple[EmbeddingRunState, ...],
        source: str,
    ) -> tuple[int, int]:
        sent = 0
        failures = 0
        for run in runs:
            try:
                await self._dispatcher.dispatch_embedding_run(embedding_run_id=run.id)
            except Exception:
                failures += 1
                logger.warning(
                    "embedding_recovery_dispatch_failed",
                    embedding_run_id=str(run.id),
                    source=source,
                )
            else:
                sent += 1
        return sent, failures


__all__ = ["EmbeddingRecoveryReport", "EmbeddingRecoveryService"]
