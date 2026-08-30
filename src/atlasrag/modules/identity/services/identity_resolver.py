from collections.abc import Callable
from uuid import UUID

from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.identity import (
    IdentityRepository,
    IdentityUnitOfWork,
    ProvisioningPolicy,
)
from atlasrag.contracts.identity_types import LocalUserIdentity
from atlasrag.modules.identity.helpers.errors import (
    IdentityAlreadyProvisioned,
    IdentityProvisioningConflict,
    LocalIdentityDisabled,
    LocalIdentityNotProvisioned,
    LocalIdentityRetired,
)


class IdentityResolver:
    def __init__(
        self,
        repository: IdentityRepository,
        uow_factory: Callable[[], IdentityUnitOfWork],
        policy: ProvisioningPolicy,
    ) -> None:
        self._repository = repository
        self._uow_factory = uow_factory
        self._policy = policy

    async def resolve(
        self,
        identity: AuthenticatedIdentity,
    ) -> UUID:
        local_identity = await self._repository.find_by_oidc_subject(
            issuer=identity.issuer,
            subject=identity.subject,
        )

        if local_identity is not None:
            self._ensure_usable(local_identity)
            return local_identity.principal_id

        if not self._policy.jit_enabled():
            raise LocalIdentityNotProvisioned

        return await self._provision(identity)

    async def _provision(self, identity: AuthenticatedIdentity) -> UUID:
        provisioning_collision = False

        try:
            async with self._uow_factory() as uow:
                local_identity = await uow.identities.find_by_oidc_subject(
                    issuer=identity.issuer,
                    subject=identity.subject,
                )

                if local_identity is not None:
                    self._ensure_usable(local_identity)
                    return local_identity.principal_id

                try:
                    principal_id = await uow.identities.provision_user(identity)
                except IdentityAlreadyProvisioned:
                    provisioning_collision = True
                    raise

                await uow.commit()
                return principal_id
        except IdentityAlreadyProvisioned:
            if not provisioning_collision:
                raise
            return await self._resolve_after_conflict(identity)

    async def _resolve_after_conflict(self, identity: AuthenticatedIdentity) -> UUID:
        async with self._uow_factory() as uow:
            local_identity = await uow.identities.find_by_oidc_subject(
                issuer=identity.issuer,
                subject=identity.subject,
            )

        if local_identity is None:
            raise IdentityProvisioningConflict

        self._ensure_usable(local_identity)
        return local_identity.principal_id

    @staticmethod
    def _ensure_usable(identity: LocalUserIdentity) -> None:
        if identity.deleted_at is not None:
            raise LocalIdentityRetired

        if not identity.is_active:
            raise LocalIdentityDisabled
