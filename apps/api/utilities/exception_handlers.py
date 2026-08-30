from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from atlasrag.contracts.identity_errors import (
    GroupCycleDetected,
    GroupMemberTypeNotAllowed,
    GroupMembershipAlreadyExists,
    GroupMembershipNotFound,
    GroupPrincipalRequired,
    GroupSelfMembership,
    InvalidPrincipalType,
    PrincipalInactive,
    PrincipalNotFound,
    PrincipalRetired,
    RoleAssignmentConflict,
    RoleAssignmentNotFound,
    RoleAssignmentRoleNotFound,
    RoleAssignmentUserNotFound,
)
from atlasrag.contracts.permission_errors import (
    LastSuperadminViolation,
    PermissionGrantConflict,
    PermissionGrantNotFound,
    PermissionNotFound,
    PermissionTargetInactive,
    PermissionTargetNotFound,
    PermissionTargetRetired,
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
    for error_type in (
        GroupMembershipNotFound,
        PermissionGrantNotFound,
        PermissionNotFound,
        PermissionTargetNotFound,
        PrincipalNotFound,
        RoleAssignmentNotFound,
        RoleAssignmentRoleNotFound,
        RoleAssignmentUserNotFound,
    ):
        application.add_exception_handler(error_type, handle_principal_not_found)
    for error_type in (
        GroupCycleDetected,
        GroupMemberTypeNotAllowed,
        GroupMembershipAlreadyExists,
        GroupPrincipalRequired,
        GroupSelfMembership,
        InvalidPrincipalType,
        LastSuperadminViolation,
        PermissionGrantConflict,
        PermissionTargetInactive,
        PermissionTargetRetired,
        PrincipalInactive,
        PrincipalRetired,
        ProtectedSuperadminRole,
        RoleAssignmentConflict,
    ):
        application.add_exception_handler(error_type, handle_principal_conflict)
