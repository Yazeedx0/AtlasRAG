import uuid
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import cast

import pytest

from atlasrag.contracts.ingestion import IngestionUnitOfWork
from atlasrag.contracts.types.chunking import ChunkContentType, ChunkDraft
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)

_NOW = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
LEASE_DURATION = timedelta(minutes=2)
MAX_ATTEMPTS = 3


def make_drafts(count: int) -> tuple[ChunkDraft, ...]:
    return tuple(
        ChunkDraft(
            chunk_index=index,
            content=f"chunk-{index}",
            content_type=ChunkContentType.TEXT,
            token_count=3,
            content_hash=f"{index:064d}",
        )
        for index in range(count)
    )


class FakeIngestionRepository:
    def __init__(self, *, completed_rowcount: int = 1) -> None:
        self._completed_rowcount = completed_rowcount
        self.completions: list[dict[str, object]] = []

    async def mark_completed(
        self,
        *,
        item_id: uuid.UUID,
        attempt_number: int,
        now: datetime,
        observed_file_hash: str,
        execution_metadata: dict[str, object],
    ) -> int:
        self.completions.append(
            {
                "item_id": item_id,
                "attempt_number": attempt_number,
                "now": now,
                "observed_file_hash": observed_file_hash,
                "execution_metadata": execution_metadata,
            }
        )
        return self._completed_rowcount


class FakeChunkRepository:
    def __init__(self, *, insert_error: Exception | None = None) -> None:
        self._insert_error = insert_error
        self.deleted_items: list[uuid.UUID] = []
        self.inserted: list[tuple[uuid.UUID, tuple[ChunkDraft, ...]]] = []

    async def delete_for_item(self, *, ingestion_item_id: uuid.UUID) -> int:
        self.deleted_items.append(ingestion_item_id)
        return 0

    async def add_all(
        self,
        *,
        ingestion_item_id: uuid.UUID,
        drafts: tuple[ChunkDraft, ...],
    ) -> None:
        if self._insert_error is not None:
            raise self._insert_error
        self.inserted.append((ingestion_item_id, drafts))
        return None


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        completed_rowcount: int = 1,
        insert_error: Exception | None = None,
    ) -> None:
        self.ingestion = FakeIngestionRepository(completed_rowcount=completed_rowcount)
        self.chunks = FakeChunkRepository(insert_error=insert_error)
        self.commits = 0
        self.exits = 0

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exits += 1
        return None

    async def commit(self) -> None:
        self.commits += 1


def make_service(uow: FakeUnitOfWork) -> IngestionLifecycleService:
    return IngestionLifecycleService(
        lambda: cast(IngestionUnitOfWork, uow),
        lease_duration=LEASE_DURATION,
        max_attempts=MAX_ATTEMPTS,
        clock=lambda: _NOW,
    )


@pytest.mark.asyncio
async def test_completion_writes_chunks_and_commits_once() -> None:
    uow = FakeUnitOfWork()
    item_id = uuid.uuid4()
    drafts = make_drafts(3)

    completed = await make_service(uow).complete_with_chunks(
        item_id=item_id,
        attempt_number=1,
        observed_file_hash="a" * 64,
        execution_metadata={"chunking": {"chunk_count": 3}},
        chunks=drafts,
    )

    assert completed is True
    assert uow.commits == 1
    assert uow.chunks.deleted_items == [item_id]
    assert uow.chunks.inserted == [(item_id, drafts)]


@pytest.mark.asyncio
async def test_previous_chunks_are_removed_before_the_new_set_is_written() -> None:
    uow = FakeUnitOfWork()
    item_id = uuid.uuid4()

    await make_service(uow).complete_with_chunks(
        item_id=item_id,
        attempt_number=2,
        observed_file_hash="b" * 64,
        execution_metadata={},
        chunks=make_drafts(2),
    )

    assert uow.chunks.deleted_items == [item_id]
    assert len(uow.chunks.inserted) == 1


@pytest.mark.asyncio
async def test_fenced_attempt_writes_no_chunks_and_never_commits() -> None:
    uow = FakeUnitOfWork(completed_rowcount=0)

    completed = await make_service(uow).complete_with_chunks(
        item_id=uuid.uuid4(),
        attempt_number=1,
        observed_file_hash="c" * 64,
        execution_metadata={},
        chunks=make_drafts(4),
    )

    assert completed is False
    assert uow.commits == 0
    assert uow.chunks.deleted_items == []
    assert uow.chunks.inserted == []


@pytest.mark.asyncio
async def test_insert_failure_propagates_without_committing() -> None:
    uow = FakeUnitOfWork(insert_error=RuntimeError("insert exploded"))

    with pytest.raises(RuntimeError):
        await make_service(uow).complete_with_chunks(
            item_id=uuid.uuid4(),
            attempt_number=1,
            observed_file_hash="d" * 64,
            execution_metadata={},
            chunks=make_drafts(5),
        )

    assert uow.commits == 0
    assert uow.exits == 1


@pytest.mark.asyncio
async def test_completion_metadata_is_forwarded_to_the_ingestion_repository() -> None:
    uow = FakeUnitOfWork()
    metadata = {"extraction": {"method": "openai_ocr"}}

    await make_service(uow).complete_with_chunks(
        item_id=uuid.uuid4(),
        attempt_number=3,
        observed_file_hash="e" * 64,
        execution_metadata=metadata,
        chunks=make_drafts(1),
    )

    assert uow.ingestion.completions[0]["execution_metadata"] == metadata
    assert uow.ingestion.completions[0]["observed_file_hash"] == "e" * 64
    assert uow.ingestion.completions[0]["attempt_number"] == 3
