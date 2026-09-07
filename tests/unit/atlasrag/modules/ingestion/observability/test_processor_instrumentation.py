import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from tests.unit.conftest import ObservabilityHarness

from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
    ExtractionMethod,
    ExtractionQualityAssessment,
)
from atlasrag.contracts.types.ingestion import ClaimedIngestionItem, LoadedArtifact
from atlasrag.contracts.types.jobs import JobType
from atlasrag.contracts.types.observability import LabelKey, MetricName, SpanName
from atlasrag.modules.ingestion.extraction.pipeline import ExtractionPipeline
from atlasrag.modules.ingestion.workers.default_processor import DefaultIngestionProcessor
from atlasrag.modules.ingestion.workers.errors import IngestionLeaseLost
from atlasrag.platform.observability import ingestion_job_context

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
_CONTENT = b"verified artifact bytes"
_DIGEST = hashlib.sha256(_CONTENT).hexdigest()
_JOB_TYPE = JobType.PROCESS_INGESTION_ITEM.value


class FakeArtifactLoader:
    def __init__(self, *, language_code: str) -> None:
        self._language_code = language_code

    async def load(self, *, artifact_id: UUID) -> LoadedArtifact:
        from atlasrag.platform.observability import update_job_context

        update_job_context(artifact_id=artifact_id, language_code=self._language_code)
        return LoadedArtifact(
            artifact_id=artifact_id,
            content=_CONTENT,
            mime_type="application/pdf",
            expected_file_hash=_DIGEST,
            observed_file_hash=_DIGEST,
            file_size_bytes=len(_CONTENT),
        )


class FakeExtractor:
    async def extract(self, *, artifact: LoadedArtifact) -> ExtractedDocument:
        return ExtractedDocument(
            blocks=(ExtractedBlock(text="block", block_type=ExtractedBlockType.PARAGRAPH),)
        )


class FakeQualityGate:
    def evaluate(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None,
    ) -> ExtractionQualityAssessment:
        return ExtractionQualityAssessment(score=1.0, reason_codes=())


class FakeLifecycle:
    def __init__(self, *, completed: bool = True) -> None:
        self._completed = completed

    async def mark_completed(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        observed_file_hash: str,
        execution_metadata: dict[str, object],
    ) -> bool:
        return self._completed


def make_processor(*, language_code: str, completed: bool = True) -> DefaultIngestionProcessor:
    return DefaultIngestionProcessor(
        artifact_loader=FakeArtifactLoader(language_code=language_code),  # type: ignore[arg-type]
        extraction_pipeline=ExtractionPipeline(
            primary=FakeExtractor(),  # type: ignore[arg-type]
            fallback=None,
            quality_gate=FakeQualityGate(),  # type: ignore[arg-type]
        ),
        lifecycle=FakeLifecycle(completed=completed),  # type: ignore[arg-type]
    )


def make_claim() -> ClaimedIngestionItem:
    return ClaimedIngestionItem(
        ingestion_item_id=uuid4(),
        document_artifact_id=uuid4(),
        attempt_number=1,
        claimed_at=_NOW,
        lease_expires_at=_NOW + timedelta(seconds=60),
    )


async def test_processing_emits_the_full_stage_span_tree(
    observability: ObservabilityHarness,
) -> None:
    processor = make_processor(language_code="ar")

    with ingestion_job_context(job_type=_JOB_TYPE):
        await processor.process(claim=make_claim())

    names = observability.span_names()
    assert SpanName.EXTRACTION.value in names
    assert SpanName.EXTRACTION_PRIMARY_OCR.value in names
    assert SpanName.EXTRACTION_QUALITY_GATE.value in names
    assert SpanName.PERSISTENCE.value in names


async def test_completion_is_counted_with_the_language_discovered_during_load(
    observability: ObservabilityHarness,
) -> None:
    processor = make_processor(language_code="ar")

    with ingestion_job_context(job_type=_JOB_TYPE):
        await processor.process(claim=make_claim())

    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_JOBS_COMPLETED_TOTAL,
            labels={
                LabelKey.JOB_TYPE: _JOB_TYPE,
                LabelKey.LANGUAGE: "ar",
                LabelKey.EXTRACTOR_METHOD: ExtractionMethod.OPENAI_OCR.value,
            },
        )
        == 1
    )


async def test_language_bound_inside_a_child_task_reaches_the_parent_context(
    observability: ObservabilityHarness,
) -> None:
    processor = make_processor(language_code="ar")

    with ingestion_job_context(job_type=_JOB_TYPE) as context:
        await asyncio.create_task(processor.process(claim=make_claim()))

        assert context.language.value == "ar"

    assert (
        observability.metrics.histogram_count(
            MetricName.PERSISTENCE_DURATION_SECONDS,
            labels={LabelKey.LANGUAGE: "ar", LabelKey.STATUS: "success"},
        )
        == 1
    )


async def test_losing_the_lease_at_persistence_is_not_counted_as_completed(
    observability: ObservabilityHarness,
) -> None:
    processor = make_processor(language_code="en", completed=False)

    with (
        ingestion_job_context(job_type=_JOB_TYPE),
        pytest.raises(IngestionLeaseLost),
    ):
        await processor.process(claim=make_claim())

    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_JOBS_COMPLETED_TOTAL,
            labels={
                LabelKey.JOB_TYPE: _JOB_TYPE,
                LabelKey.LANGUAGE: "en",
                LabelKey.EXTRACTOR_METHOD: ExtractionMethod.OPENAI_OCR.value,
            },
        )
        == 0
    )
    assert (
        observability.metrics.histogram_count(
            MetricName.PERSISTENCE_DURATION_SECONDS,
            labels={LabelKey.LANGUAGE: "en", LabelKey.STATUS: "failure"},
        )
        == 1
    )
