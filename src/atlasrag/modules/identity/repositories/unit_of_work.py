from collections.abc import Callable
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.contracts.identity import (
    GroupMembershipRepository,
    IdentityRepository,
    PrincipalRepository,
    RoleAssignmentRepository,
)
from atlasrag.contracts.permission_authorization import (
    PermissionRepository,
    SuperadminRepository,
)
from atlasrag.modules.identity.repositories.group_membership import (
    SqlAlchemyGroupMembershipRepository,
)
from atlasrag.modules.identity.repositories.identity import (
    SqlAlchemyIdentityRepository,
)
from atlasrag.modules.identity.repositories.principal import (
    SqlAlchemyPrincipalRepository,
)
from atlasrag.modules.identity.repositories.permission_repository import (
    SqlAlchemyPermissionRepository,
)
from atlasrag.modules.identity.repositories.role_assignment_repository import (
    SqlAlchemyRoleAssignmentRepository,
)
from atlasrag.modules.identity.repositories.superadmin_repository import (
    SqlAlchemySuperadminRepository,
)


class SqlAlchemyIdentityUnitOfWork:
    identities: IdentityRepository
    principals: PrincipalRepository
    memberships: GroupMembershipRepository
    permissions: PermissionRepository
    role_assignments: RoleAssignmentRepository
    superadmins: SuperadminRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "SqlAlchemyIdentityUnitOfWork":
        self._session = self._session_factory()
        self.identities = SqlAlchemyIdentityRepository(self._session)
        self.principals = SqlAlchemyPrincipalRepository(self._session)
        self.memberships = SqlAlchemyGroupMembershipRepository(self._session)
        self.permissions = SqlAlchemyPermissionRepository(self._session)
        self.role_assignments = SqlAlchemyRoleAssignmentRepository(self._session)
        self.superadmins = SqlAlchemySuperadminRepository(self._session)
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
) -> Callable[[], SqlAlchemyIdentityUnitOfWork]:
    def factory() -> SqlAlchemyIdentityUnitOfWork:
        return SqlAlchemyIdentityUnitOfWork(session_factory)

    return factory
