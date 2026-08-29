import asyncio
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import Group, Principal, Role, UserIdentifier, Users
from atlasrag.modules.identity.services.identity_resolver import IdentityResolver
from atlasrag.platform.database import Base
from atlasrag.modules.identity.repositories.identity_repository import (
    SqlAlchemyIdentityRepository,
)
from atlasrag.modules.identity.repositories.unit_of_work import (
    make_identity_unit_of_work_factory,
)


class EnabledProvisioningPolicy:
    def jit_enabled(self) -> bool:
        return True


def make_identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        issuer="https://auth.example.com/realms/atlas",
        subject="user-123",
        display_name="Integration User",
    )


async def resolve_with_fresh_lookup(
    session_factory: async_sessionmaker[AsyncSession],
    identity: AuthenticatedIdentity,
) -> UUID:
    async with session_factory() as lookup_session:
        resolver = IdentityResolver(
            SqlAlchemyIdentityRepository(lookup_session),
            make_identity_unit_of_work_factory(session_factory),
            EnabledProvisioningPolicy(),
        )
        return await resolver.resolve(identity)


async def count_rows(
    engine: AsyncEngine,
    model: type[Base],
) -> int:
    async with engine.connect() as connection:
        result = await connection.scalar(select(func.count()).select_from(model))
        assert result is not None
        return int(result)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jit_provisioning_creates_expected_identity_rows(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    engine, session_factory = identity_database
    identity = make_identity()

    principal_id = await resolve_with_fresh_lookup(session_factory, identity)

    assert await count_rows(engine, Principal) == 1
    assert await count_rows(engine, Users) == 1

    async with engine.connect() as connection:
        principal_type = await connection.scalar(
            select(Principal.type).where(Principal.id == principal_id)
        )
        identifier = (
            await connection.execute(
                select(
                    UserIdentifier.user_principal_id,
                    UserIdentifier.identifier_type,
                    UserIdentifier.issuer,
                    UserIdentifier.identifier_value,
                    UserIdentifier.normalized_value,
                    UserIdentifier.valid_to,
                ).where(
                    UserIdentifier.user_principal_id == principal_id,
                    UserIdentifier.valid_to.is_(None),
                )
            )
        ).one_or_none()

    assert principal_type == PrincipalType.USER
    assert identifier is not None
    assert identifier.user_principal_id == principal_id
    assert identifier.identifier_type == "oidc_subject"
    assert identifier.issuer == identity.issuer
    assert identifier.identifier_value == identity.subject
    assert identifier.normalized_value == identity.subject
    assert identifier.valid_to is None
    assert isinstance(principal_id, UUID)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jit_provisioning_assigns_no_roles_or_groups(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    engine, session_factory = identity_database

    await resolve_with_fresh_lookup(session_factory, make_identity())

    assert await count_rows(engine, Role) == 0
    assert await count_rows(engine, Group) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_first_login_converges_on_one_principal(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    engine, session_factory = identity_database
    identity = make_identity()

    principal_ids = await asyncio.gather(
        resolve_with_fresh_lookup(session_factory, identity),
        resolve_with_fresh_lookup(session_factory, identity),
    )

    assert principal_ids[0] == principal_ids[1]
    assert await count_rows(engine, Principal) == 1
    assert await count_rows(engine, Users) == 1

    async with engine.connect() as connection:
        identifier_count = await connection.scalar(
            select(func.count())
            .select_from(UserIdentifier)
            .where(
                UserIdentifier.identifier_type == "oidc_subject",
                UserIdentifier.issuer == identity.issuer,
                UserIdentifier.normalized_value == identity.subject,
                UserIdentifier.valid_to.is_(None),
            )
        )

    assert identifier_count == 1
