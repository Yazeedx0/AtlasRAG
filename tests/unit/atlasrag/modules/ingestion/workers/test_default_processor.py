import hashlib
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.chunking import Chunker
from atlasrag.contracts.error.extraction_errors import ExtractionFailed
from atlasrag.contracts.error.object_storage_errors import (
    ObjectNotFound,
    ObjectStorageUnavailable,
)
from atlasrag.contracts.types.chunking import ChunkDraft
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
    ExtractionMethod,
    ExtractionResult,
)
from atlasrag.contracts.types.ingestion import ClaimedIngestionItem, LoadedArtifact
from atlasrag.modules.ingestion.chunking import create_chunker
from atlasrag.modules.ingestion.extraction.pipeline import ExtractionPipeline
from atlasrag.modules.ingestion.services.artifact_loader import (
    ArtifactIntegrityMismatch,
    ArtifactLoader,
    ArtifactUnavailableForIngestion,
)
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.workers.default_processor import (
    EMPTY_CHUNK_SET,
    EXTRACTION_FAILED,
    DefaultIngestionProcessor,
)
from atlasrag.modules.ingestion.workers.errors import (
    PermanentIngestionError,
    TransientIngestionError,
)

_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


class FakeArtifactLoader:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.artifact_ids: list[UUID] = []

    async def load(self, *, artifact_id: UUID) -> LoadedArtifact:
        self.artifact_ids.append(artifact_id)
        if self._error is not None:
            raise self._error
        content = b"verified"
        digest = hashlib.sha256(content).hexdigest()
        return LoadedArtifact(
            artifact_id=uuid4(),
            content=content,
            mime_type="text/plain",
            expected_file_hash=digest,
            observed_file_hash=digest,
            file_size_bytes=len(content),
        )


def make_claim() -> ClaimedIngestionItem:
    return ClaimedIngestionItem(
        ingestion_item_id=uuid4(),
        document_artifact_id=uuid4(),
        attempt_number=1,
        claimed_at=_NOW,
        lease_expires_at=_NOW + timedelta(minutes=2),
    )


class FakeExtractionPipeline:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.artifacts: list[LoadedArtifact] = []

    async def extract(
        self,
        *,
        artifact: LoadedArtifact,
        language_code: str | None = None,
    ) -> ExtractionResult:
        self.artifacts.append(artifact)
        if self._error is not None:
            raise self._error
        return ExtractionResult(
            document=ExtractedDocument(
                blocks=(
                    ExtractedBlock(text="body", block_type=ExtractedBlockType.PARAGRAPH),
                )
            ),
            method=ExtractionMethod.OPENAI_OCR,
            fallback_used=False,
            fallback_reason=None,
            quality_score=1.0,
        )


class FakeLifecycle:
    def __init__(self, *, completed: bool = True) -> None:
        self._completed = completed
        self.completions: list[dict[str, object]] = []

    async def complete_with_chunks(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        observed_file_hash: str,
        execution_metadata: dict[str, object],
        chunks: tuple[ChunkDraft, ...],
    ) -> bool:
        self.completions.append(
            {
                "item_id": item_id,
                "attempt_number": attempt_number,
                "observed_file_hash": observed_file_hash,
                "execution_metadata": execution_metadata,
                "chunks": chunks,
            }
        )
        return self._completed


class EmptyChunker:
    def chunk(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None = None,
    ) -> tuple[ChunkDraft, ...]:
        return ()


def make_processor(
    loader: FakeArtifactLoader,
    pipeline: FakeExtractionPipeline | None = None,
    lifecycle: FakeLifecycle | None = None,
    chunker: Chunker | None = None,
) -> DefaultIngestionProcessor:
    return DefaultIngestionProcessor(
        artifact_loader=cast(ArtifactLoader, loader),
        extraction_pipeline=cast(
            ExtractionPipeline, pipeline if pipeline is not None else FakeExtractionPipeline()
        ),
        chunker=chunker if chunker is not None else create_chunker(),
        lifecycle=cast(
            IngestionLifecycleService, lifecycle if lifecycle is not None else FakeLifecycle()
        ),
    )


@pytest.mark.asyncio
async def test_processor_loads_the_claimed_artifact() -> None:
    claim = make_claim()
    loader = FakeArtifactLoader()

    await make_processor(loader).process(claim=claim)

    assert loader.artifact_ids == [claim.document_artifact_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "error_code"),
    [
        (
            ArtifactUnavailableForIngestion(artifact_id=uuid4(), status=None),
            "artifact_unavailable_for_ingestion",
        ),
        (
            ArtifactIntegrityMismatch(
                artifact_id=uuid4(),
                expected_file_hash="a" * 64,
                observed_file_hash="b" * 64,
                expected_file_size_bytes=1,
                observed_file_size_bytes=1,
            ),
            "artifact_integrity_mismatch",
        ),
        (ObjectNotFound(key="documents/missing"), "artifact_object_missing"),
    ],
)
async def test_permanent_artifact_failures_are_classified_as_permanent(
    error: Exception,
    error_code: str,
) -> None:
    processor = make_processor(FakeArtifactLoader(error=error))

    with pytest.raises(PermanentIngestionError) as raised:
        await processor.process(claim=make_claim())

    assert raised.value.error_code == error_code


@pytest.mark.asyncio
async def test_temporary_storage_failure_is_classified_as_transient() -> None:
    processor = make_processor(
        FakeArtifactLoader(
            error=ObjectStorageUnavailable(operation="get", key="documents/source"),
        )
    )

    with pytest.raises(TransientIngestionError):
        await processor.process(claim=make_claim())


@pytest.mark.asyncio
async def test_verified_artifact_is_handed_to_the_extraction_pipeline() -> None:
    loader = FakeArtifactLoader()
    pipeline = FakeExtractionPipeline()

    await make_processor(loader, pipeline).process(claim=make_claim())

    assert len(pipeline.artifacts) == 1
    assert pipeline.artifacts[0].content == b"verified"


@pytest.mark.asyncio
async def test_retryable_extraction_failure_is_classified_as_transient() -> None:
    pipeline = FakeExtractionPipeline(
        error=ExtractionFailed(
            primary_reason="http_500",
            fallback_reason="http_503",
            retryable=True,
        )
    )

    with pytest.raises(TransientIngestionError):
        await make_processor(FakeArtifactLoader(), pipeline).process(claim=make_claim())


@pytest.mark.asyncio
async def test_permanent_extraction_failure_is_classified_as_permanent() -> None:
    pipeline = FakeExtractionPipeline(
        error=ExtractionFailed(
            primary_reason="http_500",
            fallback_reason="malformed_provider_response",
            retryable=False,
        )
    )

    with pytest.raises(PermanentIngestionError) as error:
        await make_processor(FakeArtifactLoader(), pipeline).process(claim=make_claim())

    assert error.value.error_code == EXTRACTION_FAILED


@pytest.mark.asyncio
async def test_extraction_is_skipped_when_artifact_loading_fails() -> None:
    pipeline = FakeExtractionPipeline()
    loader = FakeArtifactLoader(
        error=ArtifactUnavailableForIngestion(artifact_id=uuid4(), status=None)
    )

    with pytest.raises(PermanentIngestionError):
        await make_processor(loader, pipeline).process(claim=make_claim())

    assert pipeline.artifacts == []


@pytest.mark.asyncio
async def test_successful_processing_persists_the_extraction_outcome() -> None:
    lifecycle = FakeLifecycle()
    claim = make_claim()

    await make_processor(FakeArtifactLoader(), None, lifecycle).process(claim=claim)

    assert len(lifecycle.completions) == 1
    completion = lifecycle.completions[0]
    assert completion["item_id"] == claim.ingestion_item_id
    assert completion["attempt_number"] == claim.attempt_number
    assert completion["observed_file_hash"] == hashlib.sha256(b"verified").hexdigest()
    extraction = cast(dict, completion["execution_metadata"])["extraction"]
    assert extraction["method"] == "openai_ocr"
    assert extraction["fallback_used"] is False
    assert extraction["block_count"] == 1
    chunks = cast(tuple[ChunkDraft, ...], completion["chunks"])
    assert len(chunks) == 1
    assert chunks[0].content == "body"
    chunking = cast(dict, completion["execution_metadata"])["chunking"]
    assert chunking["chunk_count"] == 1


@pytest.mark.asyncio
async def test_a_document_that_yields_no_chunks_fails_permanently() -> None:
    lifecycle = FakeLifecycle()

    with pytest.raises(PermanentIngestionError) as error:
        await make_processor(
            FakeArtifactLoader(),
            None,
            lifecycle,
            chunker=EmptyChunker(),
        ).process(claim=make_claim())

    assert error.value.error_code == EMPTY_CHUNK_SET
    assert lifecycle.completions == []


@pytest.mark.asyncio
async def test_a_lost_lease_at_completion_raises_lease_lost() -> None:
    from atlasrag.modules.ingestion.workers.errors import IngestionLeaseLost

    lifecycle = FakeLifecycle(completed=False)

    with pytest.raises(IngestionLeaseLost):
        await make_processor(FakeArtifactLoader(), None, lifecycle).process(claim=make_claim())


@pytest.mark.asyncio
async def test_nothing_is_persisted_when_extraction_fails() -> None:
    lifecycle = FakeLifecycle()
    pipeline = FakeExtractionPipeline(
        error=ExtractionFailed(
            primary_reason="http_500",
            fallback_reason="http_503",
            retryable=True,
        )
    )

    with pytest.raises(TransientIngestionError):
        await make_processor(FakeArtifactLoader(), pipeline, lifecycle).process(claim=make_claim())

    assert lifecycle.completions == []
