from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from atlasrag.contracts.error.document_errors import (
    DocumentAclExpirationInvalid,
    DocumentAclGrantConflict,
    DocumentAclGrantNotFound,
    DocumentAclPrincipalNotFound,
    DocumentArtifactConflict,
    DocumentArtifactContentTypeInvalid,
    DocumentArtifactEmpty,
    DocumentArtifactKeyInvalid,
    DocumentArtifactLanguageCodeInvalid,
    DocumentArtifactNotFound,
    DocumentArtifactStorageLocationConflict,
    DocumentArtifactTooLarge,
    DocumentArtifactVersionNotDraft,
    DocumentCanonicalKeyConflict,
    DocumentDeleted,
    DocumentNotFound,
    DocumentVersionConflict,
    DocumentVersionDocumentNotFound,
    DocumentVersionInvalidEffectiveRange,
    DocumentVersionInvalidTransition,
    DocumentVersionNotFound,
    DocumentVersionOverlap,
)
from atlasrag.contracts.error.identity_errors import (
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
from atlasrag.contracts.error.permission_errors import (
    LastSuperadminViolation,
    PermissionGrantConflict,
    PermissionGrantNotFound,
    PermissionNotFound,
    PermissionTargetInactive,
    PermissionTargetNotFound,
    PermissionTargetRetired,
    ProtectedSuperadminRole,
)


async def handle_not_found(
    request: Request,
    error: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(error)},
    )


async def handle_conflict(
    request: Request,
    error: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(error)},
    )


async def handle_document_validation_error(
    request: Request,
    error: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(error)},
    )


async def handle_payload_too_large(
    request: Request,
    error: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        content={"detail": str(error)},
    )


def register_exception_handlers(application: FastAPI) -> None:
    for error_type in (
        DocumentAclGrantNotFound,
        DocumentAclPrincipalNotFound,
        DocumentArtifactNotFound,
        DocumentNotFound,
        DocumentVersionDocumentNotFound,
        DocumentVersionNotFound,
        GroupMembershipNotFound,
        PermissionGrantNotFound,
        PermissionNotFound,
        PermissionTargetNotFound,
        PrincipalNotFound,
        RoleAssignmentNotFound,
        RoleAssignmentRoleNotFound,
        RoleAssignmentUserNotFound,
    ):
        application.add_exception_handler(error_type, handle_not_found)
    for error_type in (
        DocumentAclExpirationInvalid,
        DocumentArtifactContentTypeInvalid,
        DocumentArtifactEmpty,
        DocumentArtifactKeyInvalid,
        DocumentArtifactLanguageCodeInvalid,
        DocumentVersionInvalidEffectiveRange,
        DocumentVersionInvalidTransition,
    ):
        application.add_exception_handler(error_type, handle_document_validation_error)
    for error_type in (
        DocumentAclGrantConflict,
        DocumentArtifactConflict,
        DocumentArtifactStorageLocationConflict,
        DocumentArtifactVersionNotDraft,
        DocumentCanonicalKeyConflict,
        DocumentDeleted,
        DocumentVersionConflict,
        DocumentVersionOverlap,
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
        application.add_exception_handler(error_type, handle_conflict)
    application.add_exception_handler(
        DocumentArtifactTooLarge,
        handle_payload_too_large,
    )
