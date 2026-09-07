from atlasrag.bootstrap.core.config import get_settings
from atlasrag.platform.jobs.celery_app import celery_app, create_celery_app
from atlasrag.platform.jobs.constants import (
    PROCESS_EMBEDDING_TASK,
    PROCESS_INGESTION_TASK,
    PUBLISH_OUTBOX_TASK,
)
from atlasrag.platform.observability import (
    configure_observability,
    install_celery_observability,
)

settings = get_settings()

configure_observability(
    log_level=settings.LOG_LEVEL.value,
    json_logs=settings.LOG_JSON,
    tracing_enabled=settings.TRACING_ENABLED,
    metrics_enabled=settings.METRICS_ENABLED,
)

create_celery_app(
    broker_url=settings.CELERY_BROKER_URL,
    database_url=str(settings.DATABASE_URL),
    database_echo=settings.DATABASE_ECHO,
    outbox_publish_batch_size=settings.OUTBOX_PUBLISH_BATCH_SIZE,
    outbox_publish_lease_seconds=settings.OUTBOX_PUBLISH_LEASE_SECONDS,
    ingestion_lease_seconds=settings.INGESTION_LEASE_SECONDS,
    ingestion_heartbeat_seconds=settings.INGESTION_HEARTBEAT_SECONDS,
    ingestion_max_attempts=settings.INGESTION_MAX_ATTEMPTS,
)

install_celery_observability(
    celery_app,
    task_names=(
        PROCESS_INGESTION_TASK,
        PROCESS_EMBEDDING_TASK,
        PUBLISH_OUTBOX_TASK,
    ),
)

__all__ = ["celery_app"]
