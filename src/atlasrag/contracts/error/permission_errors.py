from uuid import UUID

from atlasrag.contracts.permissions import Permission


class PermissionEngineError(Exception):
    """Base error for application-capability authorization."""


class PermissionDenied(PermissionEngineError):
    def __init__(self, *, actor_principal_id: UUID, permission: Permission) -> None:
        self.actor_principal_id = actor_principal_id
        self.permission = permission
        super().__init__(
            f"principal {actor_principal_id} lacks permission {permission.value}"
        )


class PermissionNotFound(PermissionEngineError):
    def __init__(self, *, permission: Permission) -> None:
        self.permission = permission
        super().__init__(f"permission {permission.value} is not registered")


class PermissionGrantConflict(PermissionEngineError):
    def __init__(self, *, principal_id: UUID, permission: Permission) -> None:
        self.principal_id = principal_id
        self.permission = permission
        super().__init__(
            f"principal {principal_id} already has active permission {permission.value}"
        )


class PermissionGrantNotFound(PermissionEngineError):
    def __init__(self, *, principal_id: UUID, permission: Permission) -> None:
        self.principal_id = principal_id
        self.permission = permission
        super().__init__(
            f"principal {principal_id} has no active permission {permission.value}"
        )


class PermissionTargetNotFound(PermissionEngineError):
    def __init__(self, *, principal_id: UUID) -> None:
        self.principal_id = principal_id
        super().__init__(f"permission target principal {principal_id} not found")


class PermissionTargetInactive(PermissionEngineError):
    def __init__(self, *, principal_id: UUID) -> None:
        self.principal_id = principal_id
        super().__init__(f"permission target principal {principal_id} is inactive")


class PermissionTargetRetired(PermissionEngineError):
    def __init__(self, *, principal_id: UUID) -> None:
        self.principal_id = principal_id
        super().__init__(f"permission target principal {principal_id} is retired")


class ProtectedSuperadminRole(PermissionEngineError):
    def __init__(self, *, operation: str) -> None:
        self.operation = operation
        super().__init__(f"operation {operation} is forbidden for the superadmin role")


class LastSuperadminViolation(PermissionEngineError):
    def __init__(self, *, user_principal_id: UUID, operation: str) -> None:
        self.user_principal_id = user_principal_id
        self.operation = operation
        super().__init__(
            f"operation {operation} on principal {user_principal_id} would remove "
            "the last active superadmin"
        )


__all__ = [
    "LastSuperadminViolation",
    "PermissionDenied",
    "PermissionEngineError",
    "PermissionGrantConflict",
    "PermissionGrantNotFound",
    "PermissionNotFound",
    "PermissionTargetInactive",
    "PermissionTargetNotFound",
    "PermissionTargetRetired",
    "ProtectedSuperadminRole",
]
