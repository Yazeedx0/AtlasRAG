from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PermissionResponse(BaseModel):
    permission_key: str
    description: str | None


class PrincipalPermissionResponse(PermissionResponse):
    granted_at: datetime
    granted_by_principal_id: UUID | None
