from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AssignRoleRequest(BaseModel):
    role_id: UUID


class AssignedRoleResponse(BaseModel):
    role_id: UUID
    role_key: str
    name: str
    description: str | None
    assigned_at: datetime
    assigned_by_principal_id: UUID | None
