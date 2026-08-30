from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity: 
    issuer: str 
    subject: str 
    email: str | None = None 
    email_verified: bool | None = None 
    username: str | None = None 
    display_name: str | None = None 