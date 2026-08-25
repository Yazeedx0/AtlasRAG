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


class IdentityUnitOfWork(Protocol):
    identities: IdentityRepository

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
