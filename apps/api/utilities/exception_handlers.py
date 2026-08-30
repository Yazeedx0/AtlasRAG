from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from atlasrag.contracts.identity_errors import (
    PrincipalInactive,
    PrincipalNotFound,
    PrincipalRetired,
)
from atlasrag.contracts.permission_errors import (
    LastSuperadminViolation,
    ProtectedSuperadminRole,
)


async def handle_principal_not_found(
    request: Request,
    error: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(error)},
    )


async def handle_principal_conflict(
    request: Request,
    error: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(error)},
    )


def register_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(
        PrincipalNotFound,
        handle_principal_not_found,
    )
    for error_type in (
        LastSuperadminViolation,
        PrincipalInactive,
        PrincipalRetired,
        ProtectedSuperadminRole,
    ):
        application.add_exception_handler(error_type, handle_principal_conflict)
