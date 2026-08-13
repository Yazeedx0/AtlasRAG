"""Liveness and readiness probes.

These are infrastructure endpoints rather than API surface, so they are mounted at
the application root (outside ``/api/v1``): orchestrator probes should not have to
follow an API version bump.
"""

from fastapi import APIRouter, Response, status
from src.atlasrag.bootstrap import get_settings

from apps.api.schemas.health import LivenessResponse, ReadinessResponse

settings = get_settings()

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", status_code=status.HTTP_200_OK, summary="Liveness probe")
async def liveness() -> LivenessResponse:
    """Answer as long as the process is up; never touches dependencies."""
    return LivenessResponse(
        status="ok",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
    )


@router.get("/ready", summary="Readiness probe")
async def readiness(response: Response) -> ReadinessResponse:
    """Report whether the dependencies needed to serve traffic are reachable.

    Postgres, Redis and the vector store get registered here as they are wired into
    the lifespan; each check reports ``"ok"`` or a short failure reason. Returns 503
    when any check fails so a load balancer drops the instance without killing it.
    """
    checks: dict[str, str] = {}

    if any(result != "ok" for result in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", checks=checks)

    return ReadinessResponse(status="ready", checks=checks)
