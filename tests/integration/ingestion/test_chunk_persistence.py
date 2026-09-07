from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.contracts.types.chunking import ChunkContentType, ChunkDraft
from atlasrag.contracts.types.ingestion import IngestionStatus
from atlasrag.modules.ingestion.models import Chunk
from atlasrag.modules.ingestion.repositories import (
    ChunkRepository,
    make_ingestion_unit_of_work_factory,
)
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.knowledge.models import (
    Document,
    DocumentArtifact,
    DocumentVersion,
)

LEASE_DURATION = timedelta(minutes=2)
MAX_ATTEMPTS = 3
T0 = datetime(2026, 9, 6, 9, 30, tzinfo=UTC)
OBSERVED_FILE_HASH = "a" * 64


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


def make_drafts(count: int, *, prefix: str = "chunk") -> tuple[ChunkDraft, ...]:
    return tuple(
        ChunkDraft(
            chunk_index=index,
            content=f"{prefix}-{index}",
            content_type=ChunkContentType.TEXT,
            token_count=index + 1,
            content_hash=f"{index:064d}",
            section_title="Leave",
            section_path=("Handbook", "Leave"),
            page_start=1,
            page_end=2,
            language_code="en",
            metadata={"strategy": "heading_aware_v1"},
        )
        for index in range(count)
    )


async def add_artifact(session: AsyncSession) -> UUID:
    document_id = uuid4()
    version_id = uuid4()
    artifact_id = uuid4()

    await session.execute(
        Document.__table__.insert().values(
            id=document_id,
            canonical_key=f"canonical-{document_id}",
            title="Chunk persistence fixture",
        )
    )
    await session.execute(
        DocumentVersion.__table__.insert().values(
            id=version_id,
            document_id=document_id,
            version_label="v1",
        )
    )
    await session.execute(
        DocumentArtifact.__table__.insert().values(
            id=artifact_id,
            document_version_id=version_id,
            artifact_key=f"artifact-{artifact_id}",
            language_code="en",
            source_name="fixture.pdf",
            storage_provider="s3",
            storage_key=f"key/{artifact_id}",
            mime_type="application/pdf",
            file_hash="b" * 64,
            file_size_bytes=2048,
        )
    )
    return artifact_id


def make_service(
    session: AsyncSession,
    clock: FakeClock,
) -> IngestionLifecycleService:
    if session.bind is None:
        raise RuntimeError("Test session is not bound to an engine")
    session_factory = async_sessionmaker(
        bind=session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return IngestionLifecycleService(
        make_ingestion_unit_of_work_factory(
            session_factory,
            db_time=lambda: literal(clock()),
        ),
        lease_duration=LEASE_DURATION,
        max_attempts=MAX_ATTEMPTS,
        clock=clock,
    )


async def setup_claimed_item(
    session: AsyncSession,
    service: IngestionLifecycleService,
) -> tuple[UUID, int]:
    artifact_id = await add_artifact(session)
    await session.commit()
    run_id = await service.create_run(
        configuration={"chunking": {"strategy": "heading_aware_v1"}},
        configuration_hash="c" * 64,
        created_by_principal_id=None,
    )
    item_id = await service.add_item(
        ingestion_run_id=run_id,
        document_artifact_id=artifact_id,
    )
    claim = await service.claim(item_id=item_id)
    assert claim is not None
    return item_id, claim.attempt_number


async def read_chunks(session: AsyncSession, item_id: UUID) -> list[Chunk]:
    session.expire_all()
    rows = await session.execute(
        select(Chunk).where(Chunk.ingestion_item_id == item_id).order_by(Chunk.chunk_index)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_completion_writes_the_whole_chunk_set(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        completed = await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=attempt_number,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={"chunking": {"chunk_count": 5}},
            chunks=make_drafts(5),
        )

        item = await service.find_item(item_id=item_id)
        chunks = await read_chunks(session, item_id)

    assert completed is True
    assert item is not None
    assert item.status is IngestionStatus.COMPLETED
    assert item.observed_file_hash == OBSERVED_FILE_HASH
    assert len(chunks) == 5
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3, 4]
    assert [chunk.content for chunk in chunks] == [f"chunk-{index}" for index in range(5)]


@pytest.mark.asyncio
async def test_chunk_lineage_and_provenance_are_persisted(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=attempt_number,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={},
            chunks=make_drafts(1),
        )

        chunk = (await read_chunks(session, item_id))[0]

    assert chunk.ingestion_item_id == item_id
    assert chunk.parent_chunk_id is None
    assert chunk.content_type is ChunkContentType.TEXT
    assert chunk.section_title == "Leave"
    assert chunk.section_path == ["Handbook", "Leave"]
    assert chunk.page_start == 1
    assert chunk.page_end == 2
    assert chunk.language_code == "en"
    assert chunk.token_count == 1
    assert chunk.content_hash == f"{0:064d}"
    assert chunk.metadata_ == {"strategy": "heading_aware_v1"}
    assert chunk.created_at is not None


@pytest.mark.asyncio
async def test_retry_replaces_the_chunk_set_left_by_an_earlier_attempt(
    identity_database,
) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        repository = ChunkRepository(session)
        await repository.add_all(
            ingestion_item_id=item_id,
            drafts=make_drafts(6, prefix="first"),
        )
        await session.commit()

        completed = await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=attempt_number,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={},
            chunks=make_drafts(2, prefix="second"),
        )

        chunks = await read_chunks(session, item_id)

    assert completed is True
    assert len(chunks) == 2
    assert [chunk.content for chunk in chunks] == ["second-0", "second-1"]


@pytest.mark.asyncio
async def test_duplicate_chunk_index_is_rejected_by_the_unique_constraint(
    identity_database,
) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=attempt_number,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={},
            chunks=make_drafts(3),
        )

        repository = ChunkRepository(session)
        duplicate = ChunkDraft(
            chunk_index=1,
            content="duplicate index",
            content_type=ChunkContentType.TEXT,
            token_count=2,
            content_hash="d" * 64,
        )

        with pytest.raises(IntegrityError):
            await repository.add_all(ingestion_item_id=item_id, drafts=(duplicate,))

        await session.rollback()
        chunks = await read_chunks(session, item_id)

    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_repeated_content_hash_is_allowed(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        repeated = tuple(
            ChunkDraft(
                chunk_index=index,
                content="identical body",
                content_type=ChunkContentType.TEXT,
                token_count=2,
                content_hash="e" * 64,
            )
            for index in range(3)
        )

        completed = await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=attempt_number,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={},
            chunks=repeated,
        )

        chunks = await read_chunks(session, item_id)

    assert completed is True
    assert len({chunk.content_hash for chunk in chunks}) == 1
    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_failed_insert_leaves_no_partial_chunk_set(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        poisoned = (
            *make_drafts(400),
            ChunkDraft(
                chunk_index=400,
                content="   ",
                content_type=ChunkContentType.TEXT,
                token_count=1,
                content_hash="f" * 64,
            ),
        )

        with pytest.raises(IntegrityError):
            await service.complete_with_chunks(
                item_id=item_id,
                attempt_number=attempt_number,
                observed_file_hash=OBSERVED_FILE_HASH,
                execution_metadata={},
                chunks=poisoned,
            )

        item = await service.find_item(item_id=item_id)
        chunks = await read_chunks(session, item_id)

    assert chunks == []
    assert item is not None
    assert item.status is IngestionStatus.RUNNING
    assert item.observed_file_hash is None


@pytest.mark.asyncio
async def test_failed_retry_keeps_the_previous_complete_chunk_set(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        repository = ChunkRepository(session)
        await repository.add_all(
            ingestion_item_id=item_id,
            drafts=make_drafts(4, prefix="first"),
        )
        await session.commit()

        poisoned = (
            *make_drafts(3, prefix="second"),
            ChunkDraft(
                chunk_index=3,
                content=" ",
                content_type=ChunkContentType.TEXT,
                token_count=1,
                content_hash="0" * 64,
            ),
        )

        with pytest.raises(IntegrityError):
            await service.complete_with_chunks(
                item_id=item_id,
                attempt_number=attempt_number,
                observed_file_hash=OBSERVED_FILE_HASH,
                execution_metadata={},
                chunks=poisoned,
            )

        item = await service.find_item(item_id=item_id)
        chunks = await read_chunks(session, item_id)

    assert item is not None
    assert item.status is IngestionStatus.RUNNING
    assert len(chunks) == 4
    assert [chunk.content for chunk in chunks] == [f"first-{index}" for index in range(4)]


@pytest.mark.asyncio
async def test_stale_attempt_cannot_finalize_or_write_chunks(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        clock.advance(LEASE_DURATION * 2)
        current = await service.claim(item_id=item_id)
        assert current is not None

        completed = await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=attempt_number,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={},
            chunks=make_drafts(3, prefix="stale"),
        )

        item = await service.find_item(item_id=item_id)
        chunks = await read_chunks(session, item_id)

    assert completed is False
    assert chunks == []
    assert item is not None
    assert item.status is IngestionStatus.RUNNING
    assert item.attempt_count == current.attempt_number


@pytest.mark.asyncio
async def test_expired_lease_cannot_finalize(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        clock.advance(LEASE_DURATION * 2)

        completed = await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=attempt_number,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={},
            chunks=make_drafts(3),
        )

        chunks = await read_chunks(session, item_id)

    assert completed is False
    assert chunks == []


@pytest.mark.asyncio
async def test_stale_attempt_cannot_delete_the_winning_chunk_set(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, stale_attempt = await setup_claimed_item(session, service)

        clock.advance(LEASE_DURATION * 2)
        winner = await service.claim(item_id=item_id)
        assert winner is not None

        await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=winner.attempt_number,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={},
            chunks=make_drafts(4, prefix="winner"),
        )

        completed = await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=stale_attempt,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={},
            chunks=make_drafts(1, prefix="stale"),
        )

        chunks = await read_chunks(session, item_id)

    assert completed is False
    assert len(chunks) == 4
    assert [chunk.content for chunk in chunks] == [f"winner-{index}" for index in range(4)]


@pytest.mark.asyncio
async def test_deleting_the_ingestion_item_cascades_to_its_chunks(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        clock = FakeClock(T0)
        service = make_service(session, clock)
        item_id, attempt_number = await setup_claimed_item(session, service)

        await service.complete_with_chunks(
            item_id=item_id,
            attempt_number=attempt_number,
            observed_file_hash=OBSERVED_FILE_HASH,
            execution_metadata={},
            chunks=make_drafts(3),
        )

        repository = ChunkRepository(session)
        assert await repository.count_for_item(ingestion_item_id=item_id) == 3

        deleted = await repository.delete_for_item(ingestion_item_id=item_id)
        await session.commit()

        remaining = await repository.count_for_item(ingestion_item_id=item_id)

    assert deleted == 3
    assert remaining == 0
