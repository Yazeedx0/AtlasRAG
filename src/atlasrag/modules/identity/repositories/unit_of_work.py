from collections.abc import Callable
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.contracts.identity import (
    GroupMembershipRepository as GroupMembershipRepositoryContract,
    IdentityRepository as IdentityRepositoryContract,
    PrincipalRepository as PrincipalRepositoryContract,
    RoleAssignmentRepository as RoleAssignmentRepositoryContract,
)
from atlasrag.contracts.permission_authorization import (
    PermissionRepository as PermissionRepositoryContract,
    SuperadminRepository as SuperadminRepositoryContract,
)
from atlasrag.modules.identity.repositories.group_membership import (
    GroupMembershipRepository,
)
from atlasrag.modules.identity.repositories.identity import (
    IdentityRepository,
)
from atlasrag.modules.identity.repositories.permission_repository import (
    PermissionRepository,
)
from atlasrag.modules.identity.repositories.principal import (
    PrincipalRepository,
)
from atlasrag.modules.identity.repositories.role_assignment_repository import (
    RoleAssignmentRepository,
)
from atlasrag.modules.identity.repositories.superadmin_repository import (
    SuperadminRepository,
)


class IdentityUnitOfWork:
    identities: IdentityRepositoryContract
    principals: PrincipalRepositoryContract
    memberships: GroupMembershipRepositoryContract
    permissions: PermissionRepositoryContract
    role_assignments: RoleAssignmentRepositoryContract
    superadmins: SuperadminRepositoryContract

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "IdentityUnitOfWork":
        self._session = self._session_factory()
        self.identities = IdentityRepository(self._session)
        self.principals = PrincipalRepository(self._session)
        self.memberships = GroupMembershipRepository(self._session)
        self.permissions = PermissionRepository(self._session)
        self.role_assignments = RoleAssignmentRepository(self._session)
        self.superadmins = SuperadminRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Identity unit of work is not active")

        try:
            if exc_type is not None or session.in_transaction():
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Identity unit of work is not active")
        await session.commit()


def make_identity_unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], IdentityUnitOfWork]:
    def factory() -> IdentityUnitOfWork:
        return IdentityUnitOfWork(session_factory)

    return factory
