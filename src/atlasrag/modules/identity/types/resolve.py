from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ResolvedUserIdentity:
    user_principal_id: UUID 