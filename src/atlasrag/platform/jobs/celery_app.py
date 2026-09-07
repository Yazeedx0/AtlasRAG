from datetime import timedelta

from celery import Celery
from kombu import Queue

from atlasrag.platform.jobs.constants import (
    EMBEDDING_QUEUE,
    INGESTION_QUEUE,
    MAINTENANCE_QUEUE,
    PROCESS_EMBEDDING_TASK,
    PROCESS_INGESTION_TASK,
    PUBLISH_OUTBOX_SCHEDULE,
    PUBLISH_OUTBOX_TASK,
    RECOVER_INGESTION_LEASES_SCHEDULE,
    RECOVER_INGESTION_LEASES_TASK,
)

celery_app = Celery(
    "atlasrag",
    include=[
        "atlasrag.platform.jobs.tasks.ingestion",
        "atlasrag.platform.jobs.tasks.maintenance",
    ],
)


def create_celery_app(
    *,
    broker_url: str,
    database_url: str,
    database_echo: bool,
    outbox_publish_batch_size: int,
    outbox_publish_lease_seconds: int,
    outbox_publish_max_attempts: int = 5,
    outbox_publish_backoff_seconds: int = 5,
    outbox_publish_backoff_max_seconds: int = 600,
    outbox_publish_interval_seconds: int = 5,
    ingestion_lease_seconds: int = 60,
    ingestion_heartbeat_seconds: int = 20,
    ingestion_max_attempts: int = 3,
    ingestion_lease_recovery_batch_size: int = 100,
    ingestion_lease_recovery_interval_seconds: int = 60,
    worker_shutdown_grace_seconds: int = 30,
) -> Celery:
    celery_app.conf.update(
        broker_url=broker_url,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        timezone="UTC",
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_cancel_long_running_tasks_on_connection_loss=True,
        worker_hijack_root_logger=False,
        atlas_database_url=database_url,
        atlas_database_echo=database_echo,
        atlas_outbox_publish_batch_size=outbox_publish_batch_size,
        atlas_outbox_publish_lease_seconds=outbox_publish_lease_seconds,
        atlas_outbox_publish_max_attempts=outbox_publish_max_attempts,
        atlas_outbox_publish_backoff_seconds=outbox_publish_backoff_seconds,
        atlas_outbox_publish_backoff_max_seconds=outbox_publish_backoff_max_seconds,
        atlas_ingestion_lease_seconds=ingestion_lease_seconds,
        atlas_ingestion_heartbeat_seconds=ingestion_heartbeat_seconds,
        atlas_ingestion_max_attempts=ingestion_max_attempts,
        atlas_ingestion_lease_recovery_batch_size=ingestion_lease_recovery_batch_size,
        atlas_worker_shutdown_grace_seconds=worker_shutdown_grace_seconds,
        task_default_queue=INGESTION_QUEUE,
        task_queues=(
            Queue(INGESTION_QUEUE),
            Queue(EMBEDDING_QUEUE),
            Queue(MAINTENANCE_QUEUE),
        ),
        task_routes={
            PROCESS_INGESTION_TASK: {"queue": INGESTION_QUEUE},
            PROCESS_EMBEDDING_TASK: {"queue": EMBEDDING_QUEUE},
            PUBLISH_OUTBOX_TASK: {"queue": MAINTENANCE_QUEUE},
            RECOVER_INGESTION_LEASES_TASK: {"queue": MAINTENANCE_QUEUE},
            "atlasrag.maintenance.*": {"queue": MAINTENANCE_QUEUE},
        },
        beat_schedule={
            PUBLISH_OUTBOX_SCHEDULE: {
                "task": PUBLISH_OUTBOX_TASK,
                "schedule": timedelta(seconds=outbox_publish_interval_seconds),
                "options": {
                    "queue": MAINTENANCE_QUEUE,
                    "expires": outbox_publish_interval_seconds,
                },
            },
            RECOVER_INGESTION_LEASES_SCHEDULE: {
                "task": RECOVER_INGESTION_LEASES_TASK,
                "schedule": timedelta(
                    seconds=ingestion_lease_recovery_interval_seconds
                ),
                "options": {
                    "queue": MAINTENANCE_QUEUE,
                    "expires": ingestion_lease_recovery_interval_seconds,
                },
            },
        },
    )
    return celery_app


__all__ = ["celery_app", "create_celery_app"]
