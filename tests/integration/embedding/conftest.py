import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.contracts.types.ai_types import AiProvider
from atlasrag.contracts.types.chunking import ChunkContentType, ChunkDraft
from atlasrag.contracts.types.embedding import (
    ChunkVector,
    EmbeddingModelIdentity,
    VectorDistanceMetric,
)
from atlasrag.modules.embedding.config import DEFAULT_EMBEDDING_RUN_CONFIG
from atlasrag.modules.embedding.models import ChunkEmbedding
from atlasrag.modules.embedding.repositories import make_embedding_unit_of_work_factory
from atlasrag.modules.embedding.services import (
    EmbeddingLifecycleService,
    EmbeddingModelRegistryService,
)
from atlasrag.modules.ingestion.repositories import (
    EmbeddableChunkRepository,
    make_ingestion_unit_of_work_factory,
)
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.knowledge.models import Document, DocumentArtifact, DocumentVersion

T0 = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)
LEASE_DURATION = timedelta(minutes=2)
MAX_ATTEMPTS = 3
DIMENSION = 8


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@dataclass(frozen=True, slots=True)
class EmbeddingWorld:
    session_factory: async_sessionmaker[AsyncSession]
    clock: Callable[[], datetime]
    embedding: EmbeddingLifecycleService
    registry: EmbeddingModelRegistryService
    ingestion: IngestionLifecycleService


def embedding_run_configuration(**overrides: object) -> dict[str, object]:
    return {"embedding": {**DEFAULT_EMBEDDING_RUN_CONFIG.as_mapping(), **overrides}}


def default_model_identity(
    *,
    dimension: int = DIMENSION,
    model_name: str = "text-embedding-3-small",
    model_revision: str = "v1",
    max_input_tokens: int | None = 8191,
    distance_metric: VectorDistanceMetric = VectorDistanceMetric.COSINE,
    configuration: dict[str, object] | None = None,
) -> EmbeddingModelIdentity:
    return EmbeddingModelIdentity(
        provider=AiProvider.OPENAI,
        model_name=model_name,
        model_revision=model_revision,
        dimension=dimension,
        distance_metric=distance_metric,
        max_input_tokens=max_input_tokens,
        configuration=configuration or {},
    )


def make_world(
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> EmbeddingWorld:
    db_time = lambda: literal(clock())  # noqa: E731
    embedding_uow = make_embedding_unit_of_work_factory(
        session_factory,
        chunk_source_factory=EmbeddableChunkRepository,
        db_time=db_time,
    )
    return EmbeddingWorld(
        session_factory=session_factory,
        clock=clock,
        embedding=EmbeddingLifecycleService(
            embedding_uow,
            lease_duration=LEASE_DURATION,
            max_attempts=MAX_ATTEMPTS,
            clock=clock,
        ),
        registry=EmbeddingModelRegistryService(embedding_uow),
        ingestion=IngestionLifecycleService(
            make_ingestion_unit_of_work_factory(session_factory, db_time=db_time),
            lease_duration=LEASE_DURATION,
            max_attempts=MAX_ATTEMPTS,
            clock=clock,
        ),
    )


class RealClock:
    def __call__(self) -> datetime:
        return datetime.now(UTC)


def make_realtime_world(
    session_factory: async_sessionmaker[AsyncSession],
) -> EmbeddingWorld:
    embedding_uow = make_embedding_unit_of_work_factory(
        session_factory,
        chunk_source_factory=EmbeddableChunkRepository,
    )
    clock = RealClock()
    return EmbeddingWorld(
        session_factory=session_factory,
        clock=clock,
        embedding=EmbeddingLifecycleService(
            embedding_uow,
            lease_duration=LEASE_DURATION,
            max_attempts=MAX_ATTEMPTS,
            clock=clock,
        ),
        registry=EmbeddingModelRegistryService(embedding_uow),
        ingestion=IngestionLifecycleService(
            make_ingestion_unit_of_work_factory(session_factory),
            lease_duration=LEASE_DURATION,
            max_attempts=MAX_ATTEMPTS,
            clock=clock,
        ),
    )


@pytest_asyncio.fixture
async def embedding_world(identity_database) -> EmbeddingWorld:
    _, session_factory = identity_database
    return make_world(session_factory, FakeClock())


@pytest_asyncio.fixture
async def realtime_embedding_world(identity_database) -> EmbeddingWorld:
    _, session_factory = identity_database
    return make_realtime_world(session_factory)


def make_chunk_draft(index: int) -> ChunkDraft:
    content = f"Employees accrue annual leave in section {index}."
    return ChunkDraft(
        chunk_index=index,
        content=content,
        content_type=ChunkContentType.TEXT,
        section_title="Leave",
        section_path=("Benefits", "Leave"),
        page_start=1,
        page_end=1,
        language_code="en",
        token_count=len(content.split()),
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
    )


async def add_artifact(session: AsyncSession) -> UUID:
    document_id = uuid4()
    version_id = uuid4()
    artifact_id = uuid4()

    await session.execute(
        Document.__table__.insert().values(
            id=document_id,
            canonical_key=f"embedding-{document_id}",
            title="Embedding fixture",
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
            source_name="handbook.pdf",
            storage_provider="s3",
            storage_key=f"key/{artifact_id}",
            mime_type="application/pdf",
            file_hash="a" * 64,
            file_size_bytes=2048,
        )
    )
    await session.commit()
    return artifact_id


@dataclass(frozen=True, slots=True)
class SeededItem:
    ingestion_item_id: UUID
    chunk_ids: tuple[UUID, ...]


SeedItem = Callable[..., Awaitable[SeededItem]]


def make_seed_item(embedding_world: EmbeddingWorld) -> SeedItem:
    async def _seed(*, chunk_count: int = 3, complete: bool = True) -> SeededItem:
        async with embedding_world.session_factory() as session:
            artifact_id = await add_artifact(session)

        run_id = await embedding_world.ingestion.create_run(
            configuration={"chunking": {"strategy": "heading_aware_v1"}},
            configuration_hash="b" * 64,
            created_by_principal_id=None,
        )
        item_id = await embedding_world.ingestion.add_item(
            ingestion_run_id=run_id,
            document_artifact_id=artifact_id,
        )
        if not complete:
            return SeededItem(ingestion_item_id=item_id, chunk_ids=())

        claim = await embedding_world.ingestion.claim(item_id=item_id)
        assert claim is not None
        completed = await embedding_world.ingestion.replace_chunks_and_mark_completed(
            item_id=item_id,
            attempt_number=claim.attempt_number,
            chunks=tuple(make_chunk_draft(index) for index in range(chunk_count)),
            observed_file_hash="a" * 64,
            execution_metadata={},
        )
        assert completed is True

        async with embedding_world.session_factory() as session:
            chunk_ids = await EmbeddableChunkRepository(session).list_chunk_ids(
                ingestion_item_id=item_id
            )
        return SeededItem(ingestion_item_id=item_id, chunk_ids=chunk_ids)

    return _seed


@pytest.fixture
def seed_completed_item(embedding_world: EmbeddingWorld) -> SeedItem:
    return make_seed_item(embedding_world)


@pytest.fixture
def seed_realtime_completed_item(realtime_embedding_world: EmbeddingWorld) -> SeedItem:
    return make_seed_item(realtime_embedding_world)


def vectors_for(
    chunk_ids: tuple[UUID, ...],
    *,
    value: float = 0.25,
    dimension: int = DIMENSION,
) -> tuple[ChunkVector, ...]:
    return tuple(
        ChunkVector(chunk_id=chunk_id, values=tuple([value + index] * dimension))
        for index, chunk_id in enumerate(chunk_ids)
    )


async def stored_embeddings(world: EmbeddingWorld, model_id: UUID) -> list[ChunkEmbedding]:
    async with world.session_factory() as session:
        rows = (
            await session.execute(
                select(ChunkEmbedding).where(ChunkEmbedding.embedding_model_id == model_id)
            )
        ).scalars()
        return list(rows)
