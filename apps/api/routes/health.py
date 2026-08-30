from fastapi import APIRouter, Response, status
from src import get_settings

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
   
    checks: dict[str, str] = {}

    if any(result != "ok" for result in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", checks=checks)

    return ReadinessResponse(status="ready", checks=checks)
