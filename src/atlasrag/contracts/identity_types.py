from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class LocalUserIdentity:
    principal_id: UUID
    is_active: bool
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class PrincipalState:
    principal_id: UUID
    is_active: bool
    deleted_at: datetime | None
    type: str | None = None


@dataclass(frozen=True, slots=True)
class AssignedRole:
    role_principal_id: UUID
    role_key: str
    name: str
    description: str | None
    assigned_at: datetime
    assigned_by_principal_id: UUID | None


__all__ = ["AssignedRole", "LocalUserIdentity", "PrincipalState"]
