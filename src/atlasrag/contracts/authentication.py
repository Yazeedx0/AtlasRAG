from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True, slots=True)

class AuthenticatedIdentity: 
    issuer: str 
    subject: str 
    email: str | None = None 
    email_verified: bool | None = None 
    username: str | None = None 
    display_name: str | None = None 

class TokenVerificationError(Exception):
    """Raised when an authentication token cannot be trusted."""


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> AuthenticatedIdentity:
        """Verify a token and return the trusted external identity."""
        ...
