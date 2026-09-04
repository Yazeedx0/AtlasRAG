from datetime import UTC, datetime, timedelta

import structlog
from celery import Task

from atlasrag.platform.jobs.celery_app import celery_app
from atlasrag.platform.jobs.celery_dispatcher import CeleryTaskDispatcher
from atlasrag.platform.jobs.constants import PUBLISH_OUTBOX_TASK
from atlasrag.platform.jobs.publisher import OutboxPublishReport, OutboxPublisher
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
        unconfirmed_publications=report.unconfirmed_publications,
    )


async def _publish_pending(*, publisher: OutboxPublisher, limit: int) -> OutboxPublishReport:
    return await publisher.publish_pending(limit=limit)
