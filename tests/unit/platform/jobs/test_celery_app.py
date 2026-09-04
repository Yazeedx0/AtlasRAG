from atlasrag.platform.jobs.celery_app import create_celery_app
from atlasrag.platform.jobs.constants import (
    EMBEDDING_QUEUE,
    INGESTION_QUEUE,
    MAINTENANCE_QUEUE,
    PROCESS_EMBEDDING_TASK,
    PROCESS_INGESTION_TASK,
    PUBLISH_OUTBOX_TASK,
)


def test_celery_app_routes_stable_tasks_to_their_configured_queues() -> None:
    app = create_celery_app(
        broker_url="redis://localhost:6379/0",
        database_url="postgresql+asyncpg://atlas:atlas@localhost:5432/atlasrag",
        database_echo=False,
        outbox_publish_batch_size=100,
        outbox_publish_lease_seconds=60,
    )

    assert app.conf.task_ignore_result is True
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_routes == {
        PROCESS_INGESTION_TASK: {"queue": INGESTION_QUEUE},
        PROCESS_EMBEDDING_TASK: {"queue": EMBEDDING_QUEUE},
        PUBLISH_OUTBOX_TASK: {"queue": MAINTENANCE_QUEUE},
        "atlasrag.maintenance.*": {"queue": MAINTENANCE_QUEUE},
    }
