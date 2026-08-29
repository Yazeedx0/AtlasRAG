from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import (
    Group,
    GroupMembership,
    Principal,
    Role,
    UserRole,
    Users,
)
from atlasrag.modules.identity.repositories.effective_principal import (
    SqlAlchemyEffectivePrincipalRepository,
)
from atlasrag.modules.identity.services.effective_principal_resolver import (
    EffectivePrincipalResolver,
)

_STARTED_AT = datetime(2026, 8, 30, tzinfo=timezone.utc)
_ENDED_AT = datetime(2026, 8, 31, tzinfo=timezone.utc)


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
    is_active: bool = True,
    deleted_at: datetime | None = None,
) -> None:
    await add_principal(
        session,
        principal_id=principal_id,
        principal_type=PrincipalType.ROLE,
        is_active=is_active,
        deleted_at=deleted_at,
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
    is_active: bool = True,
    deleted_at: datetime | None = None,
) -> None:
    await add_principal(
        session,
        principal_id=principal_id,
        principal_type=PrincipalType.GROUP,
        is_active=is_active,
        deleted_at=deleted_at,
    )
    await session.execute(
        Group.__table__.insert().values(
            principal_id=principal_id,
            group_key=group_key,
            name=group_key,
        )
    )


async def seed_effective_principal_graph(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, frozenset[UUID]]:
    user_id = uuid4()
    active_role_ids = (uuid4(), uuid4())
    revoked_role_id = uuid4()
    inactive_role_id = uuid4()
    retired_role_id = uuid4()
    direct_group_ids = (uuid4(), uuid4())
    shared_parent_group_id = uuid4()
    ancestor_group_id = uuid4()
    removed_group_id = uuid4()
    inactive_group_id = uuid4()
    retired_group_id = uuid4()
    group_above_inactive_id = uuid4()

    async with session_factory() as session:
        await add_user(session, principal_id=user_id)
        await add_role(session, principal_id=active_role_ids[0], role_key="engineering")
        await add_role(session, principal_id=active_role_ids[1], role_key="employee")
        await add_role(session, principal_id=revoked_role_id, role_key="revoked")
        await add_role(
            session,
            principal_id=inactive_role_id,
            role_key="inactive",
            is_active=False,
        )
        await add_role(
            session,
            principal_id=retired_role_id,
            role_key="retired",
            is_active=False,
            deleted_at=_ENDED_AT,
        )
        await add_group(session, principal_id=direct_group_ids[0], group_key="jordan")
        await add_group(session, principal_id=direct_group_ids[1], group_key="backend")
        await add_group(
            session,
            principal_id=shared_parent_group_id,
            group_key="all-employees",
        )
        await add_group(
            session,
            principal_id=ancestor_group_id,
            group_key="organization",
        )
        await add_group(session, principal_id=removed_group_id, group_key="removed")
        await add_group(
            session,
            principal_id=inactive_group_id,
            group_key="inactive",
            is_active=False,
        )
        await add_group(
            session,
            principal_id=retired_group_id,
            group_key="retired",
            is_active=False,
            deleted_at=_ENDED_AT,
        )
        await add_group(
            session,
            principal_id=group_above_inactive_id,
            group_key="above-inactive",
        )

        await session.execute(
            UserRole.__table__.insert(),
            [
                {
                    "id": uuid4(),
                    "user_principal_id": user_id,
                    "role_principal_id": role_id,
                    "assigned_at": _STARTED_AT,
                    "revoked_at": None,
                }
                for role_id in (
                    *active_role_ids,
                    inactive_role_id,
                    retired_role_id,
                )
            ]
            + [
                {
                    "id": uuid4(),
                    "user_principal_id": user_id,
                    "role_principal_id": revoked_role_id,
                    "assigned_at": _STARTED_AT,
                    "revoked_at": _ENDED_AT,
                }
            ],
        )
        await session.execute(
            GroupMembership.__table__.insert(),
            [
                {
                    "id": uuid4(),
                    "group_principal_id": group_id,
                    "member_principal_id": user_id,
                    "member_type": PrincipalType.USER,
                    "added_at": _STARTED_AT,
                    "removed_at": None,
                }
                for group_id in (
                    *direct_group_ids,
                    inactive_group_id,
                    retired_group_id,
                )
            ]
            + [
                {
                    "id": uuid4(),
                    "group_principal_id": removed_group_id,
                    "member_principal_id": user_id,
                    "member_type": PrincipalType.USER,
                    "added_at": _STARTED_AT,
                    "removed_at": _ENDED_AT,
                },
                {
                    "id": uuid4(),
                    "group_principal_id": shared_parent_group_id,
                    "member_principal_id": direct_group_ids[0],
                    "member_type": PrincipalType.GROUP,
                    "added_at": _STARTED_AT,
                    "removed_at": None,
                },
                {
                    "id": uuid4(),
                    "group_principal_id": shared_parent_group_id,
                    "member_principal_id": direct_group_ids[1],
                    "member_type": PrincipalType.GROUP,
                    "added_at": _STARTED_AT,
                    "removed_at": None,
                },
                {
                    "id": uuid4(),
                    "group_principal_id": ancestor_group_id,
                    "member_principal_id": shared_parent_group_id,
                    "member_type": PrincipalType.GROUP,
                    "added_at": _STARTED_AT,
                    "removed_at": None,
                },
                {
                    "id": uuid4(),
                    "group_principal_id": group_above_inactive_id,
                    "member_principal_id": inactive_group_id,
                    "member_type": PrincipalType.GROUP,
                    "added_at": _STARTED_AT,
                    "removed_at": None,
                },
            ],
        )
        await session.commit()

    expected_ids = frozenset(
        {
            user_id,
            *active_role_ids,
            *direct_group_ids,
            shared_parent_group_id,
            ancestor_group_id,
        }
    )
    return user_id, expected_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_effective_principal_ids_returns_active_unique_principals(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    user_id, expected_ids = await seed_effective_principal_graph(session_factory)

    async with session_factory() as session:
        resolver = EffectivePrincipalResolver(
            SqlAlchemyEffectivePrincipalRepository(session)
        )

        result = await resolver.resolve_effective_principal_ids(user_id)

    assert result == expected_ids
    assert isinstance(result, frozenset)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_active", "deleted_at"),
    [
        (False, None),
        (False, _ENDED_AT),
    ],
)
async def test_resolve_effective_principal_ids_returns_empty_for_unusable_user(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    is_active: bool,
    deleted_at: datetime | None,
) -> None:
    _, session_factory = identity_database
    user_id = uuid4()

    async with session_factory() as session:
        await add_user(
            session,
            principal_id=user_id,
            is_active=is_active,
            deleted_at=deleted_at,
        )
        await session.commit()

    async with session_factory() as session:
        resolver = EffectivePrincipalResolver(
            SqlAlchemyEffectivePrincipalRepository(session)
        )

        result = await resolver.resolve_effective_principal_ids(user_id)

    assert result == frozenset()
