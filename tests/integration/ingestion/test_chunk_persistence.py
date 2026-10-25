import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.contracts.types.chunking import ChunkContentType, ChunkDraft
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
    ExtractionMethod,
    ExtractionResult,
)
from atlasrag.contracts.types.ingestion import IngestionStatus, LoadedArtifact
from atlasrag.modules.ingestion.chunking import (
    DEFAULT_CHUNKING_CONFIG,
    ChunkerResolver,
    WhitespaceReferenceTokenizer,
)
from atlasrag.modules.ingestion.models import Chunk
from atlasrag.modules.ingestion.repositories import make_ingestion_unit_of_work_factory
from atlasrag.modules.ingestion.services.ingestion_lifecycle import IngestionLifecycleService
from atlasrag.modules.ingestion.workers.default_processor import DefaultIngestionProcessor
from atlasrag.modules.knowledge.models import Document, DocumentArtifact, DocumentVersion

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
LEASE_DURATION = timedelta(minutes=2)


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


async def create_item(session: AsyncSession, service: IngestionLifecycleService) -> UUID:
    document_id = uuid4()
    version_id = uuid4()
    artifact_id = uuid4()
    await session.execute(
        Document.__table__.insert().values(
            id=document_id,
            canonical_key=f"chunk-test-{document_id}",
            title="Chunk test",
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
            artifact_key="source",
            language_code="en",
            source_name="source.txt",
            storage_provider="s3",
            storage_key=f"chunks/{artifact_id}",
            mime_type="text/plain",
            file_hash="a" * 64,
            file_size_bytes=1,
        )
    )
    await session.commit()
    run_id = await service.create_run(
        configuration={"chunking": DEFAULT_CHUNKING_CONFIG.as_mapping()},
        configuration_hash="b" * 64,
        created_by_principal_id=None,
    )
    return await service.add_item(ingestion_run_id=run_id, document_artifact_id=artifact_id)


def make_service(session: AsyncSession, clock: FakeClock) -> IngestionLifecycleService:
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
        max_attempts=3,
        clock=clock,
    )


def make_draft(index: int, content: str = "annual leave") -> ChunkDraft:
    return ChunkDraft(
        chunk_index=index,
        content=content,
        content_type=ChunkContentType.TEXT,
        section_title="Leave",
        section_path=("Benefits", "Leave"),
        page_start=2,
        page_end=2,
        language_code="en",
        token_count=2,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
    )


@pytest.mark.asyncio
async def test_complete_replaces_chunk_set_and_marks_item_completed(identity_database) -> None:
    _, session_factory = identity_database
    async with session_factory() as session:
        clock = FakeClock()
        service = make_service(session, clock)
        item_id = await create_item(session, service)
        claim = await service.claim(item_id=item_id)
        assert claim is not None

        completed = await service.replace_chunks_and_mark_completed(
            item_id=item_id,
            attempt_number=claim.attempt_number,
            chunks=(make_draft(0), make_draft(1, "carry over")),
            observed_file_hash="c" * 64,
            execution_metadata={"chunking": {"chunk_count": 2}},
        )
        item = await service.find_item(item_id=item_id)
        chunks = (
            await session.execute(
                select(Chunk).where(Chunk.ingestion_item_id == item_id).order_by(Chunk.chunk_index)
            )
        ).scalars().all()

    assert completed is True
    assert item is not None
    assert item.status is IngestionStatus.COMPLETED
    assert item.observed_file_hash == "c" * 64
    assert item.execution_metadata == {"chunking": {"chunk_count": 2}}
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert [chunk.section_path for chunk in chunks] == [["Benefits", "Leave"]] * 2


@pytest.mark.asyncio
async def test_duplicate_chunk_indices_roll_back_the_entire_completion(identity_database) -> None:
    _, session_factory = identity_database
    async with session_factory() as session:
        clock = FakeClock()
        service = make_service(session, clock)
        item_id = await create_item(session, service)
        claim = await service.claim(item_id=item_id)
        assert claim is not None

        with pytest.raises(IntegrityError):
            await service.replace_chunks_and_mark_completed(
                item_id=item_id,
                attempt_number=claim.attempt_number,
                chunks=(make_draft(0), make_draft(0, "duplicate")),
                observed_file_hash="c" * 64,
                execution_metadata={},
            )
        item = await service.find_item(item_id=item_id)
        count = len(
            (
                await session.execute(select(Chunk).where(Chunk.ingestion_item_id == item_id))
            ).scalars().all()
        )

    assert item is not None
    assert item.status is IngestionStatus.RUNNING
    assert count == 0


@pytest.mark.asyncio
async def test_stale_attempt_cannot_persist_chunks(identity_database) -> None:
    _, session_factory = identity_database
    async with session_factory() as session:
        clock = FakeClock()
        service = make_service(session, clock)
        item_id = await create_item(session, service)
        first = await service.claim(item_id=item_id)
        assert first is not None
        clock.advance(LEASE_DURATION + timedelta(seconds=1))
        current = await service.claim(item_id=item_id)
        assert current is not None

        stale_completed = await service.replace_chunks_and_mark_completed(
            item_id=item_id,
            attempt_number=first.attempt_number,
            chunks=(make_draft(0),),
            observed_file_hash="c" * 64,
            execution_metadata={},
        )
        current_completed = await service.replace_chunks_and_mark_completed(
            item_id=item_id,
            attempt_number=current.attempt_number,
            chunks=(make_draft(0, "current"),),
            observed_file_hash="d" * 64,
            execution_metadata={},
        )
        chunks = (
            await session.execute(select(Chunk).where(Chunk.ingestion_item_id == item_id))
        ).scalars().all()

    assert stale_completed is False
    assert current_completed is True
    assert [chunk.content for chunk in chunks] == ["current"]


@pytest.mark.asyncio
async def test_expired_lease_cannot_persist_chunks(identity_database) -> None:
    _, session_factory = identity_database
    async with session_factory() as session:
        clock = FakeClock()
        service = make_service(session, clock)
        item_id = await create_item(session, service)
        claim = await service.claim(item_id=item_id)
        assert claim is not None
        clock.advance(LEASE_DURATION + timedelta(seconds=1))

        completed = await service.replace_chunks_and_mark_completed(
            item_id=item_id,
            attempt_number=claim.attempt_number,
            chunks=(make_draft(0),),
            observed_file_hash="c" * 64,
            execution_metadata={},
        )
        item = await service.find_item(item_id=item_id)
        chunks = (
            await session.execute(select(Chunk).where(Chunk.ingestion_item_id == item_id))
        ).scalars().all()

    assert completed is False
    assert item is not None
    assert item.status is IngestionStatus.RUNNING
    assert chunks == []


@pytest.mark.asyncio
async def test_processor_persists_heading_aware_chunks_before_completion(identity_database) -> None:
    class FakeArtifactLoader:
        async def load(self, *, artifact_id: UUID) -> LoadedArtifact:
            content = b"verified"
            return LoadedArtifact(
                artifact_id=artifact_id,
                content=content,
                mime_type="text/plain",
                expected_file_hash=hashlib.sha256(content).hexdigest(),
                observed_file_hash=hashlib.sha256(content).hexdigest(),
                file_size_bytes=len(content),
                language_code="en",
            )

    class FakeExtractionPipeline:
        async def extract(
            self,
            *,
            artifact: LoadedArtifact,
            language_code: str | None = None,
        ) -> ExtractionResult:
            return ExtractionResult(
                document=ExtractedDocument(
                    blocks=(
                        ExtractedBlock("Benefits", ExtractedBlockType.HEADING, 12),
                        ExtractedBlock(
                            "Annual leave is available.",
                            ExtractedBlockType.PARAGRAPH,
                            12,
                        ),
                    )
                ),
                method=ExtractionMethod.OPENAI_OCR,
                fallback_used=False,
                fallback_reason=None,
                quality_score=1.0,
            )

    _, session_factory = identity_database
    async with session_factory() as session:
        clock = FakeClock()
        lifecycle = make_service(session, clock)
        item_id = await create_item(session, lifecycle)
        claim = await lifecycle.claim(item_id=item_id)
        assert claim is not None
        processor = DefaultIngestionProcessor(
            artifact_loader=FakeArtifactLoader(),
            extraction_pipeline=FakeExtractionPipeline(),
            lifecycle=lifecycle,
            chunker_resolver=ChunkerResolver(
                tokenizers={
                    (WhitespaceReferenceTokenizer.name, WhitespaceReferenceTokenizer.version): (
                        WhitespaceReferenceTokenizer()
                    )
                }
            ),
        )

        await processor.process(claim=claim)
        item = await lifecycle.find_item(item_id=item_id)
        chunks = (
            await session.execute(select(Chunk).where(Chunk.ingestion_item_id == item_id))
        ).scalars().all()

    assert item is not None
    assert item.status is IngestionStatus.COMPLETED
    assert item.execution_metadata["chunking"] == {
        "strategy": "heading_aware_v1",
        "reference_tokenizer": "whitespace",
        "reference_tokenizer_version": "v1",
        "chunk_count": 1,
    }
    assert len(chunks) == 1
    assert chunks[0].section_path == ["Benefits"]
    assert chunks[0].page_start == 12
