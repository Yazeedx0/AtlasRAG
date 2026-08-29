from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import Group, GroupMembership, Principal
from atlasrag.modules.identity.repositories.group_membership_repository import (
    SqlAlchemyGroupMembershipRepository,
)


async def add_group(
    session: AsyncSession,
    *,
    principal_id: UUID,
    group_key: str,
) -> None:
    await session.execute(
        Principal.__table__.insert().values(
            id=principal_id,
            type=PrincipalType.GROUP,
        )
    )
    await session.execute(
        Group.__table__.insert().values(
            principal_id=principal_id,
            group_key=group_key,
            name=group_key,
        )
    )


async def make_membership_database(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    removed_at: datetime | None = None,
) -> tuple[UUID, UUID, UUID]:
    target_group_id = uuid4()
    middle_group_id = uuid4()
    member_group_id = uuid4()
    added_at = datetime(2026, 8, 30, tzinfo=timezone.utc)

    async with session_factory() as session:
        await add_group(session, principal_id=target_group_id, group_key="target")
        await add_group(session, principal_id=middle_group_id, group_key="middle")
        await add_group(session, principal_id=member_group_id, group_key="member")
        await session.execute(
            GroupMembership.__table__.insert(),
            [
                {
                    "id": uuid4(),
                    "group_principal_id": member_group_id,
                    "member_principal_id": middle_group_id,
                    "member_type": PrincipalType.GROUP,
                    "added_at": added_at,
                },
                {
                    "id": uuid4(),
                    "group_principal_id": middle_group_id,
                    "member_principal_id": target_group_id,
                    "member_type": PrincipalType.GROUP,
                    "added_at": added_at,
                    "removed_at": removed_at,
                },
            ],
        )
        await session.commit()

    return target_group_id, member_group_id, middle_group_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_has_group_path_detects_transitive_active_path(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    target_group_id, member_group_id, _ = await make_membership_database(session_factory)

    async with session_factory() as session:
        repository = SqlAlchemyGroupMembershipRepository(session)

        result = await repository.has_group_path(
            start_group_id=member_group_id,
            target_group_id=target_group_id,
        )

    assert result is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_has_group_path_ignores_removed_membership(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    target_group_id, member_group_id, _ = await make_membership_database(
        session_factory,
        removed_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )

    async with session_factory() as session:
        repository = SqlAlchemyGroupMembershipRepository(session)

        result = await repository.has_group_path(
            start_group_id=member_group_id,
            target_group_id=target_group_id,
        )

    assert result is False
