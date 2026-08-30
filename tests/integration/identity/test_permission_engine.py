import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from scripts.bootstrap_superadmin import bootstrap_superadmin
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from atlasrag.contracts.permission_errors import (
    LastSuperadminViolation,
    PermissionGrantConflict,
    PermissionGrantNotFound,
    PermissionTargetInactive,
    PermissionTargetRetired,
    ProtectedSuperadminRole,
)
from atlasrag.contracts.permissions import ALL_MANAGEMENT_PERMISSIONS, Permission
from atlasrag.modules.identity.builtin_roles import SUPERADMIN_ROLE_KEY
from atlasrag.modules.identity.enums import IdentifierType, PrincipalType
from atlasrag.modules.identity.models import (
    Group,
    GroupMembership,
    PermissionDefinition,
    Principal,
    PrincipalPermission,
    Role,
    UserIdentifier,
    UserRole,
    Users,
)
from atlasrag.modules.identity.repositories.effective_principal import (
    EffectivePrincipalRepository,
)
from atlasrag.modules.identity.repositories.permission_repository import (
    SqlAlchemyPermissionRepository,
)
from atlasrag.modules.identity.repositories.superadmin_repository import (
    SqlAlchemySuperadminRepository,
)
from atlasrag.modules.identity.repositories.unit_of_work import (
    make_identity_unit_of_work_factory,
)
from atlasrag.modules.identity.services.effective_principal_resolver import (
    EffectivePrincipalResolver,
)
from atlasrag.modules.identity.services.permission_authorization import (
    PermissionAuthorizationService,
)
from atlasrag.modules.identity.services.permission_management import (
    PermissionManagementService,
)
from atlasrag.modules.identity.services.principal_lifecycle import PrincipalLifecycle
from atlasrag.modules.identity.services.role_assignment import RoleAssignmentService
from atlasrag.modules.knowledge.models import Document
from atlasrag.modules.knowledge.repositories.document_access import (
    DocumentAccessRepository,
)
from atlasrag.modules.knowledge.services.document_authorization import (
    DocumentAuthorizationService,
)

_GRANTED_AT = datetime(2026, 8, 29, tzinfo=UTC)
_NOW = datetime(2026, 8, 30, tzinfo=UTC)
_REVOKED_AT = datetime(2026, 8, 30, tzinfo=UTC)
_FUTURE = datetime(2026, 8, 31, tzinfo=UTC)


async def add_principal(
    session: AsyncSession,
    *,
    principal_id: UUID,
    principal_type: PrincipalType,
    is_active: bool = True,
    deleted_at: datetime | None = None,
) -> None:
    await session.execute(
        Principal.__table__.insert().values(
            id=principal_id,
            type=principal_type,
            is_active=is_active,
            deleted_at=deleted_at,
        )
    )


async def add_user(
    session: AsyncSession,
    *,
    principal_id: UUID,
    is_active: bool = True,
    deleted_at: datetime | None = None,
) -> None:
    await add_principal(
        session,
        principal_id=principal_id,
        principal_type=PrincipalType.USER,
        is_active=is_active,
        deleted_at=deleted_at,
    )
    await session.execute(
        Users.__table__.insert().values(
            principal_id=principal_id,
            display_name=str(principal_id),
        )
    )


async def add_role(
    session: AsyncSession,
    *,
    principal_id: UUID,
    role_key: str,
) -> None:
    await add_principal(
        session,
        principal_id=principal_id,
        principal_type=PrincipalType.ROLE,
    )
    await session.execute(
        Role.__table__.insert().values(
            principal_id=principal_id,
            role_key=role_key,
            name=role_key,
        )
    )


async def add_group(
    session: AsyncSession,
    *,
    principal_id: UUID,
    group_key: str,
) -> None:
    await add_principal(
        session,
        principal_id=principal_id,
        principal_type=PrincipalType.GROUP,
    )
    await session.execute(
        Group.__table__.insert().values(
            principal_id=principal_id,
            group_key=group_key,
            name=group_key,
        )
    )


async def add_membership(
    session: AsyncSession,
    *,
    group_id: UUID,
    member_id: UUID,
    member_type: PrincipalType,
) -> None:
    await session.execute(
        GroupMembership.__table__.insert().values(
            id=uuid4(),
            group_principal_id=group_id,
            member_principal_id=member_id,
            member_type=member_type,
            added_at=_GRANTED_AT,
            removed_at=None,
        )
    )


async def add_role_assignment(
    session: AsyncSession,
    *,
    user_id: UUID,
    role_id: UUID,
) -> None:
    await session.execute(
        UserRole.__table__.insert().values(
            id=uuid4(),
            user_principal_id=user_id,
            role_principal_id=role_id,
            assigned_at=_GRANTED_AT,
            assigned_by_principal_id=user_id,
            revoked_at=None,
        )
    )


async def add_permission_registry(
    session: AsyncSession,
    permissions: frozenset[Permission] = ALL_MANAGEMENT_PERMISSIONS,
) -> None:
    await session.execute(
        PermissionDefinition.__table__.insert(),
        [
            {
                "permission_key": permission.value,
                "description": permission.value,
            }
            for permission in permissions
        ],
    )


async def add_permission_grant(
    session: AsyncSession,
    *,
    principal_id: UUID,
    permission: Permission,
    granted_at: datetime = _GRANTED_AT,
    revoked_at: datetime | None = None,
) -> None:
    await session.execute(
        PrincipalPermission.__table__.insert().values(
            id=uuid4(),
            principal_id=principal_id,
            permission_key=permission.value,
            granted_at=granted_at,
            granted_by_principal_id=principal_id,
            revoked_at=revoked_at,
        )
    )


async def add_superadmin_role(session: AsyncSession) -> UUID:
    role_id = uuid4()
    await add_role(
        session,
        principal_id=role_id,
        role_key=SUPERADMIN_ROLE_KEY,
    )
    return role_id


def permission_service(session: AsyncSession) -> PermissionAuthorizationService:
    return PermissionAuthorizationService(
        effective_principal_resolver=EffectivePrincipalResolver(
            EffectivePrincipalRepository(session)
        ),
        permission_repository=SqlAlchemyPermissionRepository(session),
        clock=lambda: _NOW,
    )


async def seed_permission_path(
    session: AsyncSession,
    *,
    path: str,
) -> UUID:
    user_id = uuid4()
    await add_user(session, principal_id=user_id)
    await add_permission_registry(
        session,
        frozenset({Permission.IAM_GROUPS_MANAGE}),
    )

    grant_principal_id: UUID | None = None
    revoked_at: datetime | None = None

    if path == "user":
        grant_principal_id = user_id
    elif path == "role":
        role_id = uuid4()
        await add_role(session, principal_id=role_id, role_key="group-admin")
        await add_role_assignment(session, user_id=user_id, role_id=role_id)
        grant_principal_id = role_id
    elif path == "group":
        group_id = uuid4()
        await add_group(session, principal_id=group_id, group_key="engineering")
        await add_membership(
            session,
            group_id=group_id,
            member_id=user_id,
            member_type=PrincipalType.USER,
        )
        grant_principal_id = group_id
    elif path == "nested_group":
        child_id = uuid4()
        parent_id = uuid4()
        await add_group(session, principal_id=child_id, group_key="backend")
        await add_group(session, principal_id=parent_id, group_key="engineering")
        await add_membership(
            session,
            group_id=child_id,
            member_id=user_id,
            member_type=PrincipalType.USER,
        )
        await add_membership(
            session,
            group_id=parent_id,
            member_id=child_id,
            member_type=PrincipalType.GROUP,
        )
        grant_principal_id = parent_id
    elif path == "duplicate_group_paths":
        child_ids = (uuid4(), uuid4())
        parent_id = uuid4()
        await add_group(session, principal_id=child_ids[0], group_key="backend")
        await add_group(session, principal_id=child_ids[1], group_key="platform")
        await add_group(session, principal_id=parent_id, group_key="engineering")
        for child_id in child_ids:
            await add_membership(
                session,
                group_id=child_id,
                member_id=user_id,
                member_type=PrincipalType.USER,
            )
            await add_membership(
                session,
                group_id=parent_id,
                member_id=child_id,
                member_type=PrincipalType.GROUP,
            )
        grant_principal_id = parent_id
    elif path == "revoked":
        grant_principal_id = user_id
        revoked_at = _REVOKED_AT
    elif path == "future":
        grant_principal_id = user_id
    elif path != "none":
        raise AssertionError(f"unsupported test path {path}")

    if grant_principal_id is not None:
        await add_permission_grant(
            session,
            principal_id=grant_principal_id,
            permission=Permission.IAM_GROUPS_MANAGE,
            granted_at=_FUTURE if path == "future" else _GRANTED_AT,
            revoked_at=revoked_at,
        )

    await session.commit()
    return user_id


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("user", True),
        ("role", True),
        ("group", True),
        ("nested_group", True),
        ("duplicate_group_paths", True),
        ("none", False),
        ("revoked", False),
        ("future", False),
    ],
)
async def test_permission_authorization_uses_all_effective_principal_paths(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    path: str,
    expected: bool,
) -> None:
    _, session_factory = identity_database
    async with session_factory() as session:
        user_id = await seed_permission_path(session, path=path)

        result = await permission_service(session).is_allowed(
            user_principal_id=user_id,
            permission=Permission.IAM_GROUPS_MANAGE,
        )

    assert result is expected


@pytest.mark.integration
@pytest.mark.asyncio
async def test_permission_management_preserves_grant_history_and_allows_regrant(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    actor_id = uuid4()
    target_id = uuid4()
    async with session_factory() as session:
        await add_user(session, principal_id=actor_id)
        await add_group(session, principal_id=target_id, group_key="document-managers")
        await add_permission_registry(
            session,
            frozenset({Permission.KNOWLEDGE_DOCUMENTS_MANAGE}),
        )
        await session.commit()

    service = PermissionManagementService(
        make_identity_unit_of_work_factory(session_factory),
        clock=lambda: _NOW,
    )
    await service.grant_permission(
        principal_id=target_id,
        permission=Permission.KNOWLEDGE_DOCUMENTS_MANAGE,
        actor_principal_id=actor_id,
    )

    with pytest.raises(PermissionGrantConflict):
        await service.grant_permission(
            principal_id=target_id,
            permission=Permission.KNOWLEDGE_DOCUMENTS_MANAGE,
            actor_principal_id=actor_id,
        )

    await service.revoke_permission(
        principal_id=target_id,
        permission=Permission.KNOWLEDGE_DOCUMENTS_MANAGE,
        actor_principal_id=actor_id,
    )

    with pytest.raises(PermissionGrantNotFound):
        await service.revoke_permission(
            principal_id=target_id,
            permission=Permission.KNOWLEDGE_DOCUMENTS_MANAGE,
            actor_principal_id=actor_id,
        )

    await service.grant_permission(
        principal_id=target_id,
        permission=Permission.KNOWLEDGE_DOCUMENTS_MANAGE,
        actor_principal_id=actor_id,
    )

    async with session_factory() as session:
        grants = (
            await session.scalars(
                select(PrincipalPermission)
                .where(
                    PrincipalPermission.principal_id == target_id,
                    PrincipalPermission.permission_key
                    == Permission.KNOWLEDGE_DOCUMENTS_MANAGE.value,
                )
                .order_by(PrincipalPermission.granted_at, PrincipalPermission.id)
            )
        ).all()

    assert len(grants) == 2
    assert sum(grant.revoked_at is None for grant in grants) == 1
    assert all(grant.granted_by_principal_id == actor_id for grant in grants)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_active", "deleted_at", "error_type"),
    [
        (False, None, PermissionTargetInactive),
        (False, _REVOKED_AT, PermissionTargetRetired),
    ],
)
async def test_permission_management_rejects_unusable_principal(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    is_active: bool,
    deleted_at: datetime | None,
    error_type: type[Exception],
) -> None:
    _, session_factory = identity_database
    actor_id = uuid4()
    target_id = uuid4()
    async with session_factory() as session:
        await add_user(session, principal_id=actor_id)
        await add_user(
            session,
            principal_id=target_id,
            is_active=is_active,
            deleted_at=deleted_at,
        )
        await add_permission_registry(
            session,
            frozenset({Permission.IAM_GROUPS_MANAGE}),
        )
        await session.commit()

    service = PermissionManagementService(
        make_identity_unit_of_work_factory(session_factory),
        clock=lambda: _NOW,
    )
    with pytest.raises(error_type):
        await service.grant_permission(
            principal_id=target_id,
            permission=Permission.IAM_GROUPS_MANAGE,
            actor_principal_id=actor_id,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_rejects_duplicate_active_permission_grants(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    principal_id = uuid4()
    async with session_factory() as session:
        await add_user(session, principal_id=principal_id)
        await add_permission_registry(
            session,
            frozenset({Permission.IAM_GROUPS_MANAGE}),
        )
        await add_permission_grant(
            session,
            principal_id=principal_id,
            permission=Permission.IAM_GROUPS_MANAGE,
        )
        await add_permission_grant(
            session,
            principal_id=principal_id,
            permission=Permission.IAM_GROUPS_MANAGE,
        )

        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_superadmin_has_control_plane_permissions_without_document_acl_bypass(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    user_id = uuid4()
    document_id = uuid4()
    async with session_factory() as session:
        await add_user(session, principal_id=user_id)
        role_id = await add_superadmin_role(session)
        await add_permission_registry(session)
        for permission in ALL_MANAGEMENT_PERMISSIONS:
            await add_permission_grant(
                session,
                principal_id=role_id,
                permission=permission,
            )
        await add_role_assignment(session, user_id=user_id, role_id=role_id)
        await session.execute(
            Document.__table__.insert().values(
                id=document_id,
                canonical_key="protected-document",
                title="Protected document",
            )
        )
        await session.commit()

        authorization = permission_service(session)
        assert await authorization.is_allowed(
            user_principal_id=user_id,
            permission=Permission.IAM_PRINCIPALS_MANAGE,
        )
        assert await authorization.is_allowed(
            user_principal_id=user_id,
            permission=Permission.KNOWLEDGE_DOCUMENT_ACL_MANAGE,
        )

        effective_ids = await EffectivePrincipalResolver(
            EffectivePrincipalRepository(session)
        ).resolve_effective_principal_ids(user_id)
        can_read = await DocumentAuthorizationService(
            DocumentAccessRepository(session)
        ).can_read_document(
            document_id=document_id,
            effective_principal_ids=effective_ids,
            at=_NOW,
        )

    assert can_read is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_normal_user_is_not_superadmin_or_implicitly_authorized(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    user_id = uuid4()
    async with session_factory() as session:
        await add_user(session, principal_id=user_id)
        await add_superadmin_role(session)
        await add_permission_registry(session)
        await session.commit()

        assert not await SqlAlchemySuperadminRepository(
            session
        ).user_has_superadmin_role(user_id)
        assert not await permission_service(session).is_allowed(
            user_principal_id=user_id,
            permission=Permission.IAM_PRINCIPALS_MANAGE,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_superadmin_role_and_last_active_user_are_protected(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    first_admin_id = uuid4()
    second_admin_id = uuid4()
    async with session_factory() as session:
        await add_user(session, principal_id=first_admin_id)
        await add_user(session, principal_id=second_admin_id)
        role_id = await add_superadmin_role(session)
        await add_permission_registry(session)
        await add_permission_grant(
            session,
            principal_id=role_id,
            permission=Permission.IAM_PERMISSIONS_MANAGE,
        )
        await add_role_assignment(session, user_id=first_admin_id, role_id=role_id)
        await add_role_assignment(session, user_id=second_admin_id, role_id=role_id)
        await session.commit()

    uow_factory = make_identity_unit_of_work_factory(session_factory)
    permission_management = PermissionManagementService(
        uow_factory,
        clock=lambda: _NOW,
    )
    lifecycle = PrincipalLifecycle(uow_factory)
    role_assignments = RoleAssignmentService(uow_factory, clock=lambda: _NOW)

    with pytest.raises(ProtectedSuperadminRole):
        await permission_management.revoke_permission(
            principal_id=role_id,
            permission=Permission.IAM_PERMISSIONS_MANAGE,
            actor_principal_id=first_admin_id,
        )
    with pytest.raises(ProtectedSuperadminRole):
        await lifecycle.deactivate_principal(role_id)
    with pytest.raises(ProtectedSuperadminRole):
        await lifecycle.retire_principal(role_id)

    await role_assignments.revoke_role(
        user_principal_id=first_admin_id,
        role_principal_id=role_id,
        actor_principal_id=second_admin_id,
    )

    with pytest.raises(LastSuperadminViolation):
        await role_assignments.revoke_role(
            user_principal_id=second_admin_id,
            role_principal_id=role_id,
            actor_principal_id=second_admin_id,
        )
    with pytest.raises(LastSuperadminViolation):
        await lifecycle.deactivate_principal(second_admin_id)
    with pytest.raises(LastSuperadminViolation):
        await lifecycle.retire_principal(second_admin_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_removal_of_final_two_superadmins_leaves_one_active(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    admin_ids = (uuid4(), uuid4())
    async with session_factory() as session:
        for admin_id in admin_ids:
            await add_user(session, principal_id=admin_id)
        role_id = await add_superadmin_role(session)
        for admin_id in admin_ids:
            await add_role_assignment(session, user_id=admin_id, role_id=role_id)
        await session.commit()

    service = RoleAssignmentService(
        make_identity_unit_of_work_factory(session_factory),
        clock=lambda: _NOW,
    )
    results = await asyncio.gather(
        service.revoke_role(
            user_principal_id=admin_ids[0],
            role_principal_id=role_id,
            actor_principal_id=admin_ids[0],
        ),
        service.revoke_role(
            user_principal_id=admin_ids[1],
            role_principal_id=role_id,
            actor_principal_id=admin_ids[1],
        ),
        return_exceptions=True,
    )

    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, LastSuperadminViolation) for result in results) == 1
    async with session_factory() as session:
        active_count = await session.scalar(
            select(func.count())
            .select_from(UserRole)
            .where(
                UserRole.role_principal_id == role_id,
                UserRole.revoked_at.is_(None),
            )
        )
    assert active_count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bootstrap_assigns_superadmin_once_by_oidc_identity(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    issuer = "https://auth.example.com/realms/atlasrag"
    subject = "bootstrap-user"
    user_id = uuid4()
    async with session_factory() as session:
        await add_user(session, principal_id=user_id)
        role_id = await add_superadmin_role(session)
        await session.execute(
            UserIdentifier.__table__.insert().values(
                id=uuid4(),
                user_principal_id=user_id,
                identifier_type=IdentifierType.OIDC_SUBJECT.value,
                identifier_value=subject,
                normalized_value=subject,
                issuer=issuer,
                valid_to=None,
            )
        )
        await session.commit()

    first = await bootstrap_superadmin(
        issuer=issuer,
        subject=subject,
        session_factory=session_factory,
        clock=lambda: _NOW,
    )
    second = await bootstrap_superadmin(
        issuer=issuer,
        subject=subject,
        session_factory=session_factory,
        clock=lambda: _NOW,
    )

    assert first.user_principal_id == user_id
    assert first.assigned is True
    assert second.user_principal_id == user_id
    assert second.assigned is False
    async with session_factory() as session:
        active_count = await session.scalar(
            select(func.count())
            .select_from(UserRole)
            .where(
                UserRole.user_principal_id == user_id,
                UserRole.role_principal_id == role_id,
                UserRole.revoked_at.is_(None),
            )
        )
    assert active_count == 1
