from uuid import UUID


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


class TokenVerificationError(Exception):
    """Raised when an authentication token cannot be trusted."""


class PrincipalNotFound(IdentityError):
    """Raised when a principal does not exist."""

    def __init__(self, *, principal_id: UUID, role: str) -> None:
        self.principal_id = principal_id
        self.role = role
        super().__init__(f"{role} principal {principal_id} not found")


class PrincipalRetired(IdentityError):
    """Raised when an operation is not valid for a retired principal."""

    def __init__(self, *, principal_id: UUID, role: str) -> None:
        self.principal_id = principal_id
        self.role = role
        super().__init__(f"{role} principal {principal_id} is retired")


class PrincipalInactive(IdentityError):
    """Raised when an operation requires an active principal."""

    def __init__(self, *, principal_id: UUID, role: str) -> None:
        self.principal_id = principal_id
        self.role = role
        super().__init__(f"{role} principal {principal_id} is inactive")


class GroupPrincipalRequired(IdentityError):
    """Raised when a group operation targets a non-group principal."""

    def __init__(self, *, principal_id: UUID) -> None:
        self.principal_id = principal_id
        super().__init__(f"principal {principal_id} is not a group")


class GroupMemberTypeNotAllowed(IdentityError):
    """Raised when a group member is not a user or group."""

    def __init__(self, *, principal_id: UUID, principal_type: str | None) -> None:
        self.principal_id = principal_id
        self.principal_type = principal_type
        type_description = principal_type or "unknown"
        super().__init__(
            f"principal {principal_id} has unsupported group member type "
            f"{type_description}"
        )


class InvalidPrincipalType(IdentityError):
    """Raised when a persisted principal type cannot be parsed."""

    def __init__(self, *, principal_id: UUID, principal_type: str | None) -> None:
        self.principal_id = principal_id
        self.principal_type = principal_type
        type_description = principal_type or "unknown"
        super().__init__(
            f"principal {principal_id} has invalid persisted type {type_description}"
        )


class GroupSelfMembership(IdentityError):
    """Raised when a group is added as a member of itself."""

    def __init__(self, *, group_id: UUID, member_id: UUID) -> None:
        self.group_id = group_id
        self.member_id = member_id
        super().__init__(
            f"group {group_id} cannot contain itself as member {member_id}"
        )


class GroupCycleDetected(IdentityError):
    """Raised when a group membership would create a cycle."""

    def __init__(self, *, group_id: UUID, member_id: UUID) -> None:
        self.group_id = group_id
        self.member_id = member_id
        super().__init__(f"adding group {member_id} to group {group_id} would create a cycle")


class GroupMembershipAlreadyExists(IdentityError):
    """Raised when an active membership already exists for the group/member pair."""

    def __init__(self, *, group_id: UUID, member_id: UUID) -> None:
        self.group_id = group_id
        self.member_id = member_id
        super().__init__(
            f"active membership already exists: group {group_id}, member {member_id}"
        )


class GroupMembershipNotFound(IdentityError):
    """Raised when no active membership exists for the group/member pair."""

    def __init__(self, *, group_id: UUID, member_id: UUID) -> None:
        self.group_id = group_id
        self.member_id = member_id
        super().__init__(
            f"no active membership exists: group {group_id}, member {member_id}"
        )


class RoleAssignmentUserNotFound(IdentityError):
    def __init__(self, *, user_principal_id: UUID) -> None:
        self.user_principal_id = user_principal_id
        super().__init__(f"role assignment user principal {user_principal_id} not found")


class RoleAssignmentRoleNotFound(IdentityError):
    def __init__(self, *, role_principal_id: UUID) -> None:
        self.role_principal_id = role_principal_id
        super().__init__(f"role assignment role principal {role_principal_id} not found")


class RoleAssignmentConflict(IdentityError):
    def __init__(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
    ) -> None:
        self.user_principal_id = user_principal_id
        self.role_principal_id = role_principal_id
        super().__init__(
            f"active role assignment already exists for user {user_principal_id} "
            f"and role {role_principal_id}"
        )


class RoleAssignmentNotFound(IdentityError):
    def __init__(
        self,
        *,
        user_principal_id: UUID,
        role_principal_id: UUID,
    ) -> None:
        self.user_principal_id = user_principal_id
        self.role_principal_id = role_principal_id
        super().__init__(
            f"no active role assignment exists for user {user_principal_id} "
            f"and role {role_principal_id}"
        )

