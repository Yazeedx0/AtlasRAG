from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol
from uuid import UUID

from atlasrag.contracts.authentication import AuthenticatedIdentity


class IdentifierType(StrEnum):
    OIDC_SUBJECT = "oidc_subject"


@dataclass(frozen=True, slots=True)
class LocalUserIdentity:
    principal_id: UUID
    is_active: bool
    deleted_at: datetime | None


class IdentityRepository(Protocol):
    async def find_by_oidc_subject(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> LocalUserIdentity | None:
        """Look up a local identity by (identifier_type=oidc_subject, issuer, subject)."""
        ...

    async def provision_user(
        self,
        identity: AuthenticatedIdentity,
    ) -> UUID:
        """Atomically create Principal(type=user), User, and UserIdentifier."""
        ...


@dataclass(frozen=True, slots=True)
class PrincipalState:
    principal_id: UUID
    is_active: bool
    deleted_at: datetime | None


class PrincipalRepository(Protocol):
    async def find_by_id(self, principal_id: UUID) -> PrincipalState | None:
        ...

    async def activate(self, principal_id: UUID) -> None:
        ...

    async def deactivate(self, principal_id: UUID) -> None:
        ...

    async def retire(self, principal_id: UUID) -> None:
        ...


class UserIdentifierRepository(Protocol):
    async def close_active_for_user(
        self,
        user_principal_id: UUID,
        *,
        closed_at: datetime,
    ) -> None:
        ...


class RoleAssignmentRepository(Protocol):
    async def user_exists(self, user_principal_id: UUID) -> bool:
        ...

    async def role_exists(self, role_principal_id: UUID) -> bool:
        ...

    async def has_active_assignment(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
    ) -> bool:
        ...

    async def add_assignment(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
        assigned_by_principal_id: UUID,
        assigned_at: datetime,
    ) -> None:
        ...

    async def close_active_assignment(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
        revoked_by_principal_id: UUID,
        revoked_at: datetime,
    ) -> bool:
        ...


class IdentityUnitOfWork(Protocol):
    identities: IdentityRepository
    principals: PrincipalRepository

    async def __aenter__(self) -> "IdentityUnitOfWork":
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        ...

    async def commit(self) -> None:
        ...


class ProvisioningPolicy(Protocol):
    def jit_enabled(self) -> bool:
        ...
