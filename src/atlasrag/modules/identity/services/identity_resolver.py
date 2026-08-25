from uuid import UUID

from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.identity import IdentityRepository, LocalUserIdentity

from atlasrag.modules.identity.helpers.errors import (
    LocalIdentityDisabled,
    LocalIdentityNotProvisioned,
    LocalIdentityRetired,
)


class IdentityResolver:
    def __init__(self, repository: IdentityRepository) -> None:
        self._repository = repository

    async def resolve(
        self,
        identity: AuthenticatedIdentity,
    ) -> UUID:
        local_identity = await self._repository.find_by_oidc_subject(
            issuer=identity.issuer,
            subject=identity.subject,
        )

        if local_identity is None:
            raise LocalIdentityNotProvisioned

        self._ensure_usable(local_identity)

        return local_identity.principal_id

    @staticmethod
    def _ensure_usable(identity: LocalUserIdentity) -> None:
        if identity.deleted_at is not None:
            raise LocalIdentityRetired

        if not identity.is_active:
            raise LocalIdentityDisabled