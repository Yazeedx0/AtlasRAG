from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from atlasrag.contracts.authentication import (
    AuthenticatedIdentity,
    TokenVerificationError,
    TokenVerifier,
)


def _bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


async def get_authenticated_identity(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedIdentity:
    """Verify the request bearer token and return its external identity."""
    token_verifier: TokenVerifier | None = getattr(request.app.state, "token_verifier", None)
    if token_verifier is None:
        raise RuntimeError("Authentication verifier is not configured")

    try:
        return await token_verifier.verify(_bearer_token(authorization))
    except TokenVerificationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
