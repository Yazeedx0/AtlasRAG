from atlasrag.bootstrap.core.config import get_settings
from atlasrag.platform.jobs.celery_app import celery_app, create_celery_app

settings = get_settings()

create_celery_app(
    broker_url=settings.CELERY_BROKER_URL,
    database_url=str(settings.DATABASE_URL),
    database_echo=settings.DATABASE_ECHO,
    outbox_publish_batch_size=settings.OUTBOX_PUBLISH_BATCH_SIZE,
    outbox_publish_lease_seconds=settings.OUTBOX_PUBLISH_LEASE_SECONDS,
    ingestion_lease_seconds=settings.INGESTION_LEASE_SECONDS,
    ingestion_heartbeat_seconds=settings.INGESTION_HEARTBEAT_SECONDS,
    ingestion_max_attempts=settings.INGESTION_MAX_ATTEMPTS,
    embedding_lease_seconds=settings.EMBEDDING_LEASE_SECONDS,
    embedding_heartbeat_seconds=settings.EMBEDDING_HEARTBEAT_SECONDS,
    embedding_max_attempts=settings.EMBEDDING_MAX_ATTEMPTS,
)

__all__ = ["celery_app"]
