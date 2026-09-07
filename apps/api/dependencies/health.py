from apps.worker.celery_app import celery_app
from atlasrag.platform.database import get_engine
from atlasrag.platform.database.readiness import PostgresReadinessProbe
from atlasrag.platform.health import ReadinessService
from atlasrag.platform.jobs.readiness import (
    CeleryBrokerReadinessProbe,
    CeleryWorkerReadinessProbe,
)


def get_readiness_service() -> ReadinessService:
    return ReadinessService(
        PostgresReadinessProbe(get_engine()),
        CeleryBrokerReadinessProbe(celery_app),
        CeleryWorkerReadinessProbe(celery_app),
    )


__all__ = ["get_readiness_service"]
