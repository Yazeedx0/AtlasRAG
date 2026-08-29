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


__all__ = ["LocalUserIdentity", "PrincipalState"]
