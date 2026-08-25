class IdentityError(Exception):
    """Base error for AtlasRAG local identity operations."""


class IdentityResolutionError(IdentityError):
    """Raised when an authenticated identity cannot resolve locally."""


class LocalIdentityNotProvisioned(IdentityResolutionError):
    """Raised when no local identity exists and JIT provisioning is disabled."""


class LocalIdentityDisabled(IdentityResolutionError):
    """Raised when the local Principal exists but is disabled."""


class LocalIdentityRetired(LocalIdentityDisabled):
    """Raised when the local Principal has been permanently retired."""


class IdentityDataIntegrityError(IdentityResolutionError):
    """Raised when persisted identity data violates required invariants."""


class IdentityProvisioningError(IdentityResolutionError):
    """Base error for local identity provisioning failures."""


class IdentityProvisioningConflict(IdentityProvisioningError):
    """Raised when a provisioning race cannot be resolved by re-querying."""