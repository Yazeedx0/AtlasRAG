from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from atlasrag.contracts.authorization_types import DocumentPermission
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import Group, Principal, Role, Users
from atlasrag.modules.knowledge.models import Document, DocumentACL
from atlasrag.modules.knowledge.repositories.document_access import (
    DocumentAccessRepository,
)
from atlasrag.modules.knowledge.services.document_authorization import (
    DocumentAuthorizationService,
)

_EVALUATED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)


async def add_principal(
    session: AsyncSession,
    *,
    principal_id: UUID,
    principal_type: PrincipalType,
) -> None:
    await session.execute(
        Principal.__table__.insert().values(
            id=principal_id,
            type=principal_type,
        )
    )

    if principal_type is PrincipalType.USER:
        await session.execute(
            Users.__table__.insert().values(
                principal_id=principal_id,
                display_name=str(principal_id),
            )
        )
    elif principal_type is PrincipalType.ROLE:
        await session.execute(
            Role.__table__.insert().values(
                principal_id=principal_id,
                role_key=f"role-{principal_id}",
                name=str(principal_id),
            )
        )
    elif principal_type is PrincipalType.GROUP:
        await session.execute(
            Group.__table__.insert().values(
                principal_id=principal_id,
                group_key=f"group-{principal_id}",
                name=str(principal_id),
            )
        )


async def add_document(
    session: AsyncSession,
    *,
    document_id: UUID,
) -> None:
    await session.execute(
        Document.__table__.insert().values(
            id=document_id,
            canonical_key=f"document-{document_id}",
            title=str(document_id),
        )
    )


async def add_grant(
    session: AsyncSession,
    *,
    document_id: UUID,
    principal_id: UUID,
    permission: DocumentPermission = DocumentPermission.READ,
    granted_at: datetime = _EVALUATED_AT,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> None:
    await session.execute(
        DocumentACL.__table__.insert().values(
            id=uuid4(),
            document_id=document_id,
            principal_id=principal_id,
            permission=permission,
            granted_at=granted_at,
            revoked_at=revoked_at,
            expires_at=expires_at,
        )
    )


async def can_read_document(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    document_id: UUID,
    principal_ids: frozenset[UUID],
) -> bool:
    async with session_factory() as session:
        service = DocumentAuthorizationService(
            DocumentAccessRepository(session)
        )
        return await service.can_read_document(
            document_id=document_id,
            effective_principal_ids=principal_ids,
            at=_EVALUATED_AT,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_can_read_document_accepts_active_direct_user_read_grant(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    user_id = uuid4()

    async with session_factory() as session:
        await add_principal(
            session,
            principal_id=user_id,
            principal_type=PrincipalType.USER,
        )
        await add_document(session, document_id=document_id)
        await add_grant(
            session,
            document_id=document_id,
            principal_id=user_id,
            granted_at=_EVALUATED_AT,
            expires_at=_EVALUATED_AT + timedelta(days=1),
        )
        await session.commit()

    result = await can_read_document(
        session_factory,
        document_id=document_id,
        principal_ids=frozenset({user_id}),
    )

    assert result is True


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("principal_type", [PrincipalType.ROLE, PrincipalType.GROUP])
async def test_can_read_document_accepts_active_role_or_group_read_grant(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    principal_type: PrincipalType,
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    principal_id = uuid4()

    async with session_factory() as session:
        await add_principal(
            session,
            principal_id=principal_id,
            principal_type=principal_type,
        )
        await add_document(session, document_id=document_id)
        await add_grant(
            session,
            document_id=document_id,
            principal_id=principal_id,
            granted_at=_EVALUATED_AT - timedelta(days=1),
        )
        await session.commit()

    result = await can_read_document(
        session_factory,
        document_id=document_id,
        principal_ids=frozenset({uuid4(), principal_id}),
    )

    assert result is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_can_read_document_accepts_manage_grant(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    principal_id = uuid4()

    async with session_factory() as session:
        await add_principal(
            session,
            principal_id=principal_id,
            principal_type=PrincipalType.USER,
        )
        await add_document(session, document_id=document_id)
        await add_grant(
            session,
            document_id=document_id,
            principal_id=principal_id,
            permission=DocumentPermission.MANAGE,
            granted_at=_EVALUATED_AT - timedelta(days=1),
        )
        await session.commit()

    result = await can_read_document(
        session_factory,
        document_id=document_id,
        principal_ids=frozenset({principal_id}),
    )

    assert result is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_can_read_document_denies_when_no_grant_exists(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database

    result = await can_read_document(
        session_factory,
        document_id=uuid4(),
        principal_ids=frozenset({uuid4()}),
    )

    assert result is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_can_read_document_denies_grant_for_another_principal(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    granted_principal_id = uuid4()
    effective_principal_id = uuid4()

    async with session_factory() as session:
        await add_principal(
            session,
            principal_id=granted_principal_id,
            principal_type=PrincipalType.USER,
        )
        await add_principal(
            session,
            principal_id=effective_principal_id,
            principal_type=PrincipalType.USER,
        )
        await add_document(session, document_id=document_id)
        await add_grant(
            session,
            document_id=document_id,
            principal_id=granted_principal_id,
            granted_at=_EVALUATED_AT - timedelta(days=1),
        )
        await session.commit()

    result = await can_read_document(
        session_factory,
        document_id=document_id,
        principal_ids=frozenset({effective_principal_id}),
    )

    assert result is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_can_read_document_denies_grant_for_another_document(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    granted_document_id = uuid4()
    requested_document_id = uuid4()
    principal_id = uuid4()

    async with session_factory() as session:
        await add_principal(
            session,
            principal_id=principal_id,
            principal_type=PrincipalType.USER,
        )
        await add_document(session, document_id=granted_document_id)
        await add_document(session, document_id=requested_document_id)
        await add_grant(
            session,
            document_id=granted_document_id,
            principal_id=principal_id,
            granted_at=_EVALUATED_AT - timedelta(days=1),
        )
        await session.commit()

    result = await can_read_document(
        session_factory,
        document_id=requested_document_id,
        principal_ids=frozenset({principal_id}),
    )

    assert result is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_can_read_document_denies_revoked_grant(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    principal_id = uuid4()

    async with session_factory() as session:
        await add_principal(
            session,
            principal_id=principal_id,
            principal_type=PrincipalType.USER,
        )
        await add_document(session, document_id=document_id)
        await add_grant(
            session,
            document_id=document_id,
            principal_id=principal_id,
            granted_at=_EVALUATED_AT - timedelta(days=2),
            revoked_at=_EVALUATED_AT - timedelta(days=1),
        )
        await session.commit()

    result = await can_read_document(
        session_factory,
        document_id=document_id,
        principal_ids=frozenset({principal_id}),
    )

    assert result is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_can_read_document_denies_grant_at_expiration_boundary(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    principal_id = uuid4()

    async with session_factory() as session:
        await add_principal(
            session,
            principal_id=principal_id,
            principal_type=PrincipalType.USER,
        )
        await add_document(session, document_id=document_id)
        await add_grant(
            session,
            document_id=document_id,
            principal_id=principal_id,
            granted_at=_EVALUATED_AT - timedelta(days=1),
            expires_at=_EVALUATED_AT,
        )
        await session.commit()

    result = await can_read_document(
        session_factory,
        document_id=document_id,
        principal_ids=frozenset({principal_id}),
    )

    assert result is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_can_read_document_denies_future_grant(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    principal_id = uuid4()

    async with session_factory() as session:
        await add_principal(
            session,
            principal_id=principal_id,
            principal_type=PrincipalType.USER,
        )
        await add_document(session, document_id=document_id)
        await add_grant(
            session,
            document_id=document_id,
            principal_id=principal_id,
            granted_at=_EVALUATED_AT + timedelta(seconds=1),
        )
        await session.commit()

    result = await can_read_document(
        session_factory,
        document_id=document_id,
        principal_ids=frozenset({principal_id}),
    )

    assert result is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_access_repository_denies_empty_principal_collection(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        repository = DocumentAccessRepository(session)

        result = await repository.has_active_read_grant(
            document_id=uuid4(),
            principal_ids=frozenset(),
            at=_EVALUATED_AT,
        )

    assert result is False
