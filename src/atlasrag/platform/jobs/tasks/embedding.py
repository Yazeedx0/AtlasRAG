import uuid
from datetime import UTC, datetime, timedelta

import structlog
from celery import Task

from atlasrag.bootstrap.core.config import get_settings
from atlasrag.contracts.embedding import EmbeddingProvider
from atlasrag.contracts.types.embedding import EmbeddingModelState
from atlasrag.modules.embedding.repositories import make_embedding_unit_of_work_factory
from atlasrag.modules.embedding.services.embedding_lifecycle import (
    EmbeddingLifecycleService,
)
from atlasrag.modules.embedding.services.recovery import EmbeddingRecoveryService
from atlasrag.modules.embedding.workers.default_processor import (
    DefaultEmbeddingProcessor,
    ProviderFactory,
)
from atlasrag.modules.embedding.workers.heartbeat import EmbeddingLeaseHeartbeat
from atlasrag.modules.embedding.workers.job_handler import EmbeddingJobHandler
from atlasrag.modules.ingestion.repositories import EmbeddableChunkRepository
from atlasrag.platform.ai.embeddings import create_embedding_provider
from atlasrag.platform.jobs.celery_app import celery_app
from atlasrag.platform.jobs.constants import PROCESS_EMBEDDING_TASK, RECOVER_EMBEDDING_TASK
from atlasrag.platform.jobs.embedding_dispatcher import CeleryEmbeddingRunDispatcher
from atlasrag.platform.jobs.worker_runtime import get_worker_async_runtime

logger = structlog.get_logger(__name__)


@celery_app.task(
    name=PROCESS_EMBEDDING_TASK,
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def process_embedding_run(self: Task, embedding_run_id: str) -> None:
    run_id = uuid.UUID(embedding_run_id)
    configuration = self.app.conf
    runtime = get_worker_async_runtime()
    runtime.initialize(
        database_url=configuration.atlas_database_url,
        database_echo=configuration.atlas_database_echo,
    )

    settings = get_settings()
    lifecycle = EmbeddingLifecycleService(
        make_embedding_unit_of_work_factory(
            runtime.session_factory,
            chunk_source_factory=EmbeddableChunkRepository,
        ),
        dispatcher=CeleryEmbeddingRunDispatcher(self.app),
        lease_duration=timedelta(seconds=configuration.atlas_embedding_lease_seconds),
        max_attempts=configuration.atlas_embedding_max_attempts,
        clock=lambda: datetime.now(UTC),
    )

    def provider_factory(model: EmbeddingModelState) -> EmbeddingProvider:
        return create_embedding_provider(settings, provider=model.provider)

    runtime.run(
        _handle_run(
            run_id=run_id,
            lifecycle=lifecycle,
            provider_factory=provider_factory,
            heartbeat_seconds=configuration.atlas_embedding_heartbeat_seconds,
        )
    )
    logger.info("embedding_run_processed", embedding_run_id=embedding_run_id)


async def _handle_run(
    *,
    run_id: uuid.UUID,
    lifecycle: EmbeddingLifecycleService,
    provider_factory: ProviderFactory,
    heartbeat_seconds: int,
) -> None:
    handler = EmbeddingJobHandler(
        lifecycle=lifecycle,
        processor=DefaultEmbeddingProcessor(
            lifecycle=lifecycle,
            provider_factory=provider_factory,
        ),
        heartbeat=EmbeddingLeaseHeartbeat(
            lifecycle,
            interval=timedelta(seconds=heartbeat_seconds),
        ),
    )
    await handler.handle(embedding_run_id=run_id)


@celery_app.task(
    name=RECOVER_EMBEDDING_TASK,
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def recover_embeddings(self: Task) -> None:
    configuration = self.app.conf
    runtime = get_worker_async_runtime()
    runtime.initialize(
        database_url=configuration.atlas_database_url,
        database_echo=configuration.atlas_database_echo,
    )

    def clock() -> datetime:
        return datetime.now(UTC)

    uow_factory = make_embedding_unit_of_work_factory(
        runtime.session_factory,
        chunk_source_factory=EmbeddableChunkRepository,
    )
    dispatcher = CeleryEmbeddingRunDispatcher(self.app)
    lifecycle = EmbeddingLifecycleService(
        uow_factory,
        dispatcher=dispatcher,
        lease_duration=timedelta(seconds=configuration.atlas_embedding_lease_seconds),
        max_attempts=configuration.atlas_embedding_max_attempts,
        clock=clock,
    )
    report = runtime.run(
        EmbeddingRecoveryService(
            uow_factory=uow_factory,
            lifecycle=lifecycle,
            dispatcher=dispatcher,
            pending_age=timedelta(
                seconds=configuration.atlas_embedding_pending_recovery_age_seconds
            ),
            batch_size=configuration.atlas_embedding_recovery_batch_size,
            clock=clock,
        ).recover()
    )
    logger.info(
        "embedding_recovery_completed",
        redispatched_pending=report.redispatched_pending,
        redispatched_expired=report.redispatched_expired,
        failed_exhausted=report.failed_exhausted,
        dispatch_failures=report.dispatch_failures,
    )


__all__ = ["process_embedding_run", "recover_embeddings"]
