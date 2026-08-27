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


class IdentityAlreadyProvisioned(IdentityProvisioningError):
    """Raised by the persistence layer when the active-identity uniqueness
    constraint rejects an insert: another transaction won the race for the
    same (identifier_type, issuer, normalized_value). This is the expected,
    recoverable signal on a concurrent first login, not a hard failure."""


class IdentityProvisioningConflict(IdentityProvisioningError):
    """Raised by the application layer when, after an IdentityAlreadyProvisioned
    collision, rollback and a fresh re-query still cannot find the winning
    identity. Unlike IdentityAlreadyProvisioned, this is not expected during
    normal concurrent provisioning and indicates the race could not be
    resolved."""


class PrincipalNotFound(IdentityError):
    """Raised when a principal does not exist."""


class PrincipalRetired(IdentityError):
    """Raised when an operation is not valid for a retired principal."""