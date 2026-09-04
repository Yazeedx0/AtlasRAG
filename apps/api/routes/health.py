from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from src import get_settings

from apps.api.dependencies.health import get_readiness_service
from apps.api.schemas.health import LivenessResponse, ReadinessResponse
from atlasrag.platform.health import ReadinessService

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


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
)
async def readiness(
    response: Response,
    service: Annotated[ReadinessService, Depends(get_readiness_service)],
) -> ReadinessResponse:
    report = await service.check()
    checks = {"database": "ok" if report.database_ready else "unavailable"}

    if not report.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", checks=checks)

    return ReadinessResponse(status="ready", checks=checks)
