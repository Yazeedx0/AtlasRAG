from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from apps.api.dependencies.authentication import get_authenticated_identity
from apps.api.dependencies.identity import get_local_principal_id
from apps.api.schemas.iam.authentication import AuthenticatedUserResponse
from atlasrag.contracts.authentication import AuthenticatedIdentity

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get(
    "/me",
    response_model=AuthenticatedUserResponse,
    status_code=status.HTTP_200_OK,
)
async def authenticated_user(
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    principal_id: Annotated[UUID, Depends(get_local_principal_id)],
) -> AuthenticatedUserResponse:
    """Return the authenticated external identity and local Principal mapping."""
    return AuthenticatedUserResponse(
        principal_id=principal_id,
        issuer=identity.issuer,
        subject=identity.subject,
        email=identity.email,
        email_verified=identity.email_verified,
        username=identity.username,
        display_name=identity.display_name,
    )
