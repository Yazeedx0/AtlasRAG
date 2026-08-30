from uuid import UUID

from pydantic import BaseModel


class AuthenticatedUserResponse(BaseModel):
    principal_id: UUID
    issuer: str
    subject: str
    email: str | None = None
    email_verified: bool | None = None
    username: str | None = None
    display_name: str | None = None
