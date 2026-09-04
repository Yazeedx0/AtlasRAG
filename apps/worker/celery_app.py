from atlasrag.bootstrap.core.config import get_settings
from atlasrag.platform.jobs.celery_app import celery_app, create_celery_app

settings = get_settings()

create_celery_app(
    broker_url=settings.CELERY_BROKER_URL,
    database_url=str(settings.DATABASE_URL),
    database_echo=settings.DATABASE_ECHO,
    outbox_publish_batch_size=settings.OUTBOX_PUBLISH_BATCH_SIZE,
    outbox_publish_lease_seconds=settings.OUTBOX_PUBLISH_LEASE_SECONDS,
)

__all__ = ["celery_app"]
