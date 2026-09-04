from atlasrag.platform.database import get_engine
from atlasrag.platform.database.readiness import PostgresReadinessProbe
from atlasrag.platform.health import ReadinessService


def get_readiness_service() -> ReadinessService:
    return ReadinessService(PostgresReadinessProbe(get_engine()))


__all__ = ["get_readiness_service"]
