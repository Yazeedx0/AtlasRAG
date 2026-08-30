from typing import Protocol
from atlasrag.contracts.types.authentication_types import AuthenticatedIdentity
from atlasrag.contracts.error.identity_errors import TokenVerificationError

class TokenVerifier(Protocol):
    async def verify(self, token: str) -> AuthenticatedIdentity:
        """Verify a token and return the trusted external identity."""
        ...
