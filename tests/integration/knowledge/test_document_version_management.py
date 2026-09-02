import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from apps.api.dependencies.knowledge import make_knowledge_unit_of_work_factory
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from atlasrag.contracts.types.authorization import DocumentVersionStatus
from atlasrag.contracts.error.document_errors import (
    DocumentVersionConflict,
    DocumentVersionDocumentNotFound,
    DocumentVersionInvalidEffectiveRange,
    DocumentVersionInvalidTransition,
    DocumentVersionNotFound,
    DocumentVersionOverlap,
)
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import Principal, Users
from atlasrag.modules.knowledge.models import Document, DocumentVersion
from atlasrag.modules.knowledge.services.document_version_management import (
    DocumentVersionManagementService,
)

_CREATED_AT = datetime(2026, 8, 1, tzinfo=UTC)
_V1_EFFECTIVE_FROM = datetime(2026, 1, 1, tzinfo=UTC)
_V2_EFFECTIVE_FROM = datetime(2026, 9, 1, tzinfo=UTC)


async def add_user(session: AsyncSession, *, principal_id: UUID) -> None:
    await session.execute(
        Principal.__table__.insert().values(
            id=principal_id,
            type=PrincipalType.USER,
        )
    )
    await session.execute(
        Users.__table__.insert().values(
            principal_id=principal_id,
            display_name=str(principal_id),
        )
    )


async def add_document(
    session: AsyncSession,
    *,
    document_id: UUID,
    deleted_at: datetime | None = None,
) -> None:
    await session.execute(
        Document.__table__.insert().values(
            id=document_id,
            canonical_key=f"document-{document_id}",
            title=str(document_id),
            deleted_at=deleted_at,
        )
    )


def make_service(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    clock: datetime = _CREATED_AT,
) -> DocumentVersionManagementService:
    return DocumentVersionManagementService(
        make_knowledge_unit_of_work_factory(session_factory),
        clock=lambda: clock,
    )


# --- Creation ---------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_version_creates_draft(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    actor_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await add_user(session, principal_id=actor_id)
        await session.commit()

    service = make_service(session_factory)
    version = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=actor_id,
        metadata={"note": "initial"},
    )

    assert version.status is DocumentVersionStatus.DRAFT
    assert version.published_at is None
    assert version.effective_from is None
    assert version.effective_to is None
    assert version.metadata == {"note": "initial"}
    assert version.created_by_principal_id == actor_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_version_requires_existing_document(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    service = make_service(session_factory)

    with pytest.raises(DocumentVersionDocumentNotFound):
        await service.create_version(
            document_id=uuid4(),
            version_label="v1",
            actor_principal_id=None,
            metadata={},
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_version_rejects_deleted_document(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id, deleted_at=_CREATED_AT)
        await session.commit()

    service = make_service(session_factory)
    with pytest.raises(DocumentVersionDocumentNotFound):
        await service.create_version(
            document_id=document_id,
            version_label="v1",
            actor_principal_id=None,
            metadata={},
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_version_rejects_duplicate_label(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )

    with pytest.raises(DocumentVersionConflict):
        await service.create_version(
            document_id=document_id,
            version_label="v1",
            actor_principal_id=None,
            metadata={},
        )


# --- Publishing ---------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_first_version(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )

    published = await service.publish_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )

    assert published.status is DocumentVersionStatus.PUBLISHED
    assert published.published_at == _CREATED_AT
    assert published.effective_from == _V1_EFFECTIVE_FROM
    assert published.effective_to is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_closes_previous_open_version(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    v1 = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=v1.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )

    v2 = await service.create_version(
        document_id=document_id,
        version_label="v2",
        actor_principal_id=None,
        metadata={},
    )
    v2_published = await service.publish_version(
        document_id=document_id,
        version_id=v2.version_id,
        effective_from=_V2_EFFECTIVE_FROM,
    )

    v1_after = await service.get_version(document_id=document_id, version_id=v1.version_id)

    assert v1_after.status is DocumentVersionStatus.PUBLISHED
    assert v1_after.effective_to == _V2_EFFECTIVE_FROM
    assert v2_published.effective_from == _V2_EFFECTIVE_FROM
    assert v2_published.effective_to is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_supports_scheduled_future_effective_date(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    future_effective_from = _CREATED_AT + timedelta(days=30)

    published = await service.publish_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_from=future_effective_from,
    )

    assert published.effective_from == future_effective_from
    assert published.published_at == _CREATED_AT


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_rejects_non_draft_version(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )

    with pytest.raises(DocumentVersionInvalidTransition):
        await service.publish_version(
            document_id=document_id,
            version_id=draft.version_id,
            effective_from=_V1_EFFECTIVE_FROM,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_missing_version_raises_not_found(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    with pytest.raises(DocumentVersionNotFound):
        await service.publish_version(
            document_id=document_id,
            version_id=uuid4(),
            effective_from=_V1_EFFECTIVE_FROM,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_publishing_never_produces_overlapping_effective_periods(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    v1 = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    v2 = await service.create_version(
        document_id=document_id,
        version_label="v2",
        actor_principal_id=None,
        metadata={},
    )

    results = await asyncio.gather(
        service.publish_version(
            document_id=document_id,
            version_id=v1.version_id,
            effective_from=_V1_EFFECTIVE_FROM,
        ),
        service.publish_version(
            document_id=document_id,
            version_id=v2.version_id,
            effective_from=_V1_EFFECTIVE_FROM,
        ),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(
        failures[0],
        (DocumentVersionOverlap, DocumentVersionInvalidEffectiveRange),
    )

    async with session_factory() as session:
        published_count = await session.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.status == DocumentVersionStatus.PUBLISHED,
            )
        )
    assert published_count == 1


# --- Temporal -----------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_adjacent_effective_ranges_are_allowed(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    v1 = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=v1.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )
    v2 = await service.create_version(
        document_id=document_id,
        version_label="v2",
        actor_principal_id=None,
        metadata={},
    )

    published = await service.publish_version(
        document_id=document_id,
        version_id=v2.version_id,
        effective_from=_V2_EFFECTIVE_FROM,
    )

    assert published.effective_from == _V2_EFFECTIVE_FROM


@pytest.mark.integration
@pytest.mark.asyncio
async def test_withdraw_rejects_effective_to_not_after_effective_from(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )

    with pytest.raises(DocumentVersionInvalidEffectiveRange):
        await service.withdraw_version(
            document_id=document_id,
            version_id=draft.version_id,
            effective_to=_V1_EFFECTIVE_FROM,
        )


# --- Withdrawal -----------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_withdraw_published_version(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )

    withdrawn_at = _V1_EFFECTIVE_FROM + timedelta(days=200)
    withdrawn = await service.withdraw_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_to=withdrawn_at,
    )

    assert withdrawn.status is DocumentVersionStatus.WITHDRAWN
    assert withdrawn.effective_to == withdrawn_at


@pytest.mark.integration
@pytest.mark.asyncio
async def test_withdraw_rejects_draft(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )

    with pytest.raises(DocumentVersionInvalidTransition):
        await service.withdraw_version(
            document_id=document_id,
            version_id=draft.version_id,
            effective_to=_CREATED_AT,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_withdraw_rejects_already_withdrawn(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )
    withdrawn_at = _V1_EFFECTIVE_FROM + timedelta(days=10)
    await service.withdraw_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_to=withdrawn_at,
    )

    with pytest.raises(DocumentVersionInvalidTransition):
        await service.withdraw_version(
            document_id=document_id,
            version_id=draft.version_id,
            effective_to=withdrawn_at + timedelta(days=1),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_withdraw_rejects_archived(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )
    withdrawn_at = _V1_EFFECTIVE_FROM + timedelta(days=10)
    await service.withdraw_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_to=withdrawn_at,
    )
    await service.archive_version(document_id=document_id, version_id=draft.version_id)

    with pytest.raises(DocumentVersionInvalidTransition):
        await service.withdraw_version(
            document_id=document_id,
            version_id=draft.version_id,
            effective_to=withdrawn_at + timedelta(days=1),
        )


# --- Archive -----------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_archive_withdrawn_version(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )
    withdrawn_at = _V1_EFFECTIVE_FROM + timedelta(days=10)
    await service.withdraw_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_to=withdrawn_at,
    )

    archived = await service.archive_version(document_id=document_id, version_id=draft.version_id)

    assert archived.status is DocumentVersionStatus.ARCHIVED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_archive_rejects_draft(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )

    with pytest.raises(DocumentVersionInvalidTransition):
        await service.archive_version(document_id=document_id, version_id=draft.version_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_archive_rejects_published_directly(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    draft = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=draft.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )

    with pytest.raises(DocumentVersionInvalidTransition):
        await service.archive_version(document_id=document_id, version_id=draft.version_id)


# --- Queries -----------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_versions_returns_all_versions_in_creation_order(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    v1 = await make_service(session_factory, clock=_CREATED_AT).create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    v2 = await make_service(
        session_factory,
        clock=_CREATED_AT + timedelta(days=1),
    ).create_version(
        document_id=document_id,
        version_label="v2",
        actor_principal_id=None,
        metadata={},
    )

    versions = await make_service(session_factory).list_versions(document_id=document_id)

    assert [version.version_id for version in versions] == [v1.version_id, v2.version_id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_version_raises_not_found_for_missing_version(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    with pytest.raises(DocumentVersionNotFound):
        await service.get_version(document_id=document_id, version_id=uuid4())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_effective_version_returns_current_effective_version(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    v1 = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=v1.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )
    v2 = await service.create_version(
        document_id=document_id,
        version_label="v2",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=v2.version_id,
        effective_from=_V2_EFFECTIVE_FROM,
    )

    effective_now = await service.get_effective_version(
        document_id=document_id,
        at=_V2_EFFECTIVE_FROM + timedelta(days=1),
    )
    effective_historical = await service.get_effective_version(
        document_id=document_id,
        at=_V1_EFFECTIVE_FROM + timedelta(days=1),
    )

    assert effective_now is not None
    assert effective_now.version_id == v2.version_id
    assert effective_historical is not None
    assert effective_historical.version_id == v1.version_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_effective_version_returns_none_when_no_version_is_effective(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )

    effective = await service.get_effective_version(document_id=document_id, at=_CREATED_AT)

    assert effective is None


# --- Transactions --------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_rejects_effective_from_before_open_version_start(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    v1 = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    await service.publish_version(
        document_id=document_id,
        version_id=v1.version_id,
        effective_from=_V1_EFFECTIVE_FROM,
    )

    v2 = await service.create_version(
        document_id=document_id,
        version_label="v2",
        actor_principal_id=None,
        metadata={},
    )

    with pytest.raises(DocumentVersionInvalidEffectiveRange):
        await service.publish_version(
            document_id=document_id,
            version_id=v2.version_id,
            effective_from=_V1_EFFECTIVE_FROM - timedelta(days=1),
        )

    v1_after = await service.get_version(document_id=document_id, version_id=v1.version_id)
    v2_after = await service.get_version(document_id=document_id, version_id=v2.version_id)
    assert v1_after.status is DocumentVersionStatus.PUBLISHED
    assert v1_after.effective_to is None
    assert v2_after.status is DocumentVersionStatus.DRAFT


@pytest.mark.integration
@pytest.mark.asyncio
async def test_db_constraint_failure_rolls_back_publication(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()

    async with session_factory() as session:
        await add_document(session, document_id=document_id)
        await session.commit()

    service = make_service(session_factory)
    v1 = await service.create_version(
        document_id=document_id,
        version_label="v1",
        actor_principal_id=None,
        metadata={},
    )
    v2 = await service.create_version(
        document_id=document_id,
        version_label="v2",
        actor_principal_id=None,
        metadata={},
    )

    results = await asyncio.gather(
        service.publish_version(
            document_id=document_id,
            version_id=v1.version_id,
            effective_from=_V1_EFFECTIVE_FROM,
        ),
        service.publish_version(
            document_id=document_id,
            version_id=v2.version_id,
            effective_from=_V1_EFFECTIVE_FROM,
        ),
        return_exceptions=True,
    )

    failed_version_id = (
        v1.version_id if isinstance(results[0], DocumentVersionOverlap) else v2.version_id
    )
    failed_version_after = await service.get_version(
        document_id=document_id,
        version_id=failed_version_id,
    )
    assert failed_version_after.status is DocumentVersionStatus.DRAFT
    assert failed_version_after.effective_from is None
