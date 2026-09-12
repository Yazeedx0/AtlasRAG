from celery import Celery
from kombu import Queue

from atlasrag.platform.jobs.constants import (
    EMBEDDING_QUEUE,
    INGESTION_QUEUE,
    MAINTENANCE_QUEUE,
    PROCESS_EMBEDDING_TASK,
    PROCESS_INGESTION_TASK,
    PUBLISH_OUTBOX_TASK,
)

celery_app = Celery(
    "atlasrag",
    include=[
        "atlasrag.platform.jobs.tasks.embedding",
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
    ingestion_lease_seconds: int = 60,
    ingestion_heartbeat_seconds: int = 20,
    ingestion_max_attempts: int = 3,
    embedding_lease_seconds: int = 120,
    embedding_heartbeat_seconds: int = 30,
    embedding_max_attempts: int = 3,
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
        atlas_database_url=database_url,
        atlas_database_echo=database_echo,
        atlas_outbox_publish_batch_size=outbox_publish_batch_size,
        atlas_outbox_publish_lease_seconds=outbox_publish_lease_seconds,
        atlas_ingestion_lease_seconds=ingestion_lease_seconds,
        atlas_ingestion_heartbeat_seconds=ingestion_heartbeat_seconds,
        atlas_ingestion_max_attempts=ingestion_max_attempts,
        atlas_embedding_lease_seconds=embedding_lease_seconds,
        atlas_embedding_heartbeat_seconds=embedding_heartbeat_seconds,
        atlas_embedding_max_attempts=embedding_max_attempts,
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
            "atlasrag.maintenance.*": {"queue": MAINTENANCE_QUEUE},
        },
    )
    return celery_app


__all__ = ["celery_app", "create_celery_app"]
