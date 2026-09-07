from datetime import UTC, datetime, timedelta

import structlog
from celery import Task

from atlasrag.modules.ingestion.repositories.unit_of_work import (
    make_ingestion_unit_of_work_factory,
)
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
    LeaseRecoveryReport,
)
from atlasrag.platform.jobs.backoff import ExponentialBackoff
from atlasrag.platform.jobs.celery_app import celery_app
from atlasrag.platform.jobs.celery_dispatcher import CeleryTaskDispatcher
from atlasrag.platform.jobs.constants import (
    PUBLISH_OUTBOX_TASK,
    RECOVER_INGESTION_LEASES_TASK,
)
from atlasrag.platform.jobs.publisher import OutboxPublisher, OutboxPublishReport
from atlasrag.platform.jobs.unit_of_work import make_job_outbox_unit_of_work_factory
from atlasrag.platform.jobs.worker_runtime import get_worker_async_runtime

logger = structlog.get_logger(__name__)


@celery_app.task(
    name=PUBLISH_OUTBOX_TASK,
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def publish_outbox(self: Task) -> None:
    runtime = get_worker_async_runtime()
    configuration = self.app.conf
    runtime.initialize(
        database_url=configuration.atlas_database_url,
        database_echo=configuration.atlas_database_echo,
    )
    publisher = OutboxPublisher(
        make_job_outbox_unit_of_work_factory(runtime.session_factory),
        CeleryTaskDispatcher(self.app),
        lease_duration=timedelta(seconds=configuration.atlas_outbox_publish_lease_seconds),
        clock=lambda: datetime.now(UTC),
        max_attempts=configuration.atlas_outbox_publish_max_attempts,
        backoff=ExponentialBackoff(
            base=timedelta(seconds=configuration.atlas_outbox_publish_backoff_seconds),
            maximum=timedelta(
                seconds=configuration.atlas_outbox_publish_backoff_max_seconds
            ),
        ),
    )
    report = runtime.run(
        _publish_pending(
            publisher=publisher,
            limit=configuration.atlas_outbox_publish_batch_size,
        )
    )
    logger.info(
        "outbox_publish_completed",
        claimed=report.claimed,
        published=report.published,
        dispatch_failures=report.dispatch_failures,
        unknown_job_types=report.unknown_job_types,
        dead_lettered=report.dead_lettered,
        unconfirmed_publications=report.unconfirmed_publications,
        unconfirmed_terminal_failures=report.unconfirmed_terminal_failures,
    )


@celery_app.task(
    name=RECOVER_INGESTION_LEASES_TASK,
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def recover_ingestion_leases(self: Task) -> None:
    runtime = get_worker_async_runtime()
    configuration = self.app.conf
    runtime.initialize(
        database_url=configuration.atlas_database_url,
        database_echo=configuration.atlas_database_echo,
    )
    lifecycle = IngestionLifecycleService(
        make_ingestion_unit_of_work_factory(runtime.session_factory),
        lease_duration=timedelta(seconds=configuration.atlas_ingestion_lease_seconds),
        max_attempts=configuration.atlas_ingestion_max_attempts,
        clock=lambda: datetime.now(UTC),
    )
    report = runtime.run(
        _recover_expired_items(
            lifecycle=lifecycle,
            limit=configuration.atlas_ingestion_lease_recovery_batch_size,
        )
    )
    logger.info(
        "ingestion_lease_recovery_completed",
        scanned=report.scanned,
        requeued=report.requeued,
        finalized=report.finalized,
        skipped=report.skipped,
    )


async def _publish_pending(*, publisher: OutboxPublisher, limit: int) -> OutboxPublishReport:
    return await publisher.publish_pending(limit=limit)


async def _recover_expired_items(
    *,
    lifecycle: IngestionLifecycleService,
    limit: int,
) -> LeaseRecoveryReport:
    return await lifecycle.recover_expired_items(limit=limit)


__all__ = ["publish_outbox", "recover_ingestion_leases"]
