import hashlib
from uuid import uuid4

import pytest
from tests.unit.conftest import ObservabilityHarness

from atlasrag.contracts.error.extraction_errors import (
    ExtractionFailed,
    ExtractionProviderPermanentError,
    ExtractionProviderTransientError,
)
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
    ExtractionMethod,
    ExtractionQualityAssessment,
)
from atlasrag.contracts.types.ingestion import LoadedArtifact
from atlasrag.contracts.types.observability import LabelKey, MetricName, SpanName
from atlasrag.modules.ingestion.extraction.pipeline import ExtractionPipeline
from atlasrag.platform.observability import ingestion_job_context

pytestmark = pytest.mark.unit

_ARABIC_TEXT = "نص مستخرج من الوثيقة"


def make_artifact() -> LoadedArtifact:
    content = b"verified artifact"
    digest = hashlib.sha256(content).hexdigest()
    return LoadedArtifact(
        artifact_id=uuid4(),
        content=content,
        mime_type="application/pdf",
        expected_file_hash=digest,
        observed_file_hash=digest,
        file_size_bytes=len(content),
    )


def make_document(text: str, *, blocks: int = 1) -> ExtractedDocument:
    return ExtractedDocument(
        blocks=tuple(
            ExtractedBlock(text=text, block_type=ExtractedBlockType.PARAGRAPH, page_number=1)
            for _ in range(blocks)
        )
    )


class FakeExtractor:
    def __init__(
        self,
        *,
        text: str = "extracted",
        blocks: int = 1,
        error: Exception | None = None,
    ) -> None:
        self._text = text
        self._blocks = blocks
        self._error = error

    async def extract(self, *, artifact: LoadedArtifact) -> ExtractedDocument:
        if self._error is not None:
            raise self._error
        return make_document(self._text, blocks=self._blocks)


class FakeQualityGate:
    def evaluate(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None,
    ) -> ExtractionQualityAssessment:
        return ExtractionQualityAssessment(score=0.9, reason_codes=())


def make_pipeline(
    *,
    primary: FakeExtractor,
    fallback: FakeExtractor | None = None,
) -> ExtractionPipeline:
    return ExtractionPipeline(
        primary=primary,  # type: ignore[arg-type]
        fallback=fallback,  # type: ignore[arg-type]
        quality_gate=FakeQualityGate(),  # type: ignore[arg-type]
    )


async def test_primary_success_emits_its_span_tree_and_counter(
    observability: ObservabilityHarness,
) -> None:
    pipeline = make_pipeline(primary=FakeExtractor(blocks=3))

    with ingestion_job_context(job_type="ingestion.process", language_code="en"):
        await pipeline.extract(artifact=make_artifact())

    names = observability.span_names()
    assert SpanName.EXTRACTION.value in names
    assert SpanName.EXTRACTION_PRIMARY_OCR.value in names
    assert SpanName.EXTRACTION_QUALITY_GATE.value in names
    assert SpanName.EXTRACTION_FALLBACK_VLM.value not in names
    assert (
        observability.metrics.counter_value(
            MetricName.EXTRACTION_PRIMARY_SUCCESS_TOTAL,
            labels={
                LabelKey.LANGUAGE: "en",
                LabelKey.EXTRACTOR_METHOD: ExtractionMethod.OPENAI_OCR.value,
            },
        )
        == 1
    )


async def test_block_counts_are_recorded_per_language(
    observability: ObservabilityHarness,
) -> None:
    pipeline = make_pipeline(primary=FakeExtractor(text=_ARABIC_TEXT, blocks=7))

    with ingestion_job_context(job_type="ingestion.process", language_code="ar"):
        await pipeline.extract(artifact=make_artifact())

    labels = {
        LabelKey.LANGUAGE: "ar",
        LabelKey.EXTRACTOR_METHOD: ExtractionMethod.OPENAI_OCR.value,
    }
    assert (
        observability.metrics.histogram_sum(
            MetricName.EXTRACTION_BLOCKS_PER_DOCUMENT,
            labels=labels,
        )
        == 7
    )


async def test_fallback_emits_the_fallback_span_and_a_categorized_reason(
    observability: ObservabilityHarness,
) -> None:
    pipeline = make_pipeline(
        primary=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason="timeout",
            )
        ),
        fallback=FakeExtractor(blocks=2),
    )

    with ingestion_job_context(job_type="ingestion.process", language_code="ar"):
        result = await pipeline.extract(artifact=make_artifact())

    assert result.fallback_used is True
    assert SpanName.EXTRACTION_FALLBACK_VLM.value in observability.span_names()
    assert (
        observability.metrics.counter_value(
            MetricName.EXTRACTION_FALLBACK_TOTAL,
            labels={
                LabelKey.LANGUAGE: "ar",
                LabelKey.EXTRACTOR_METHOD: ExtractionMethod.VLM.value,
                LabelKey.FALLBACK_REASON: "timeout",
            },
        )
        == 1
    )


async def test_extraction_duration_is_labelled_with_the_method_that_ran(
    observability: ObservabilityHarness,
) -> None:
    pipeline = make_pipeline(
        primary=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason="timeout",
            )
        ),
        fallback=FakeExtractor(),
    )

    with ingestion_job_context(job_type="ingestion.process", language_code="en"):
        await pipeline.extract(artifact=make_artifact())

    assert (
        observability.metrics.histogram_count(
            MetricName.EXTRACTION_DURATION_SECONDS,
            labels={
                LabelKey.LANGUAGE: "en",
                LabelKey.EXTRACTOR_METHOD: ExtractionMethod.VLM.value,
                LabelKey.STATUS: "success",
            },
        )
        == 1
    )


async def test_total_extraction_failure_is_counted_with_retryability(
    observability: ObservabilityHarness,
) -> None:
    pipeline = make_pipeline(
        primary=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason="timeout",
            )
        ),
        fallback=FakeExtractor(
            error=ExtractionProviderPermanentError(
                method=ExtractionMethod.VLM,
                reason="unsupported_mime_type",
            )
        ),
    )

    with (
        ingestion_job_context(job_type="ingestion.process", language_code="ar"),
        pytest.raises(ExtractionFailed),
    ):
        await pipeline.extract(artifact=make_artifact())

    assert (
        observability.metrics.counter_value(
            MetricName.EXTRACTION_FAILURES_TOTAL,
            labels={
                LabelKey.LANGUAGE: "ar",
                LabelKey.ERROR_CODE: "other",
                LabelKey.RETRYABLE: "false",
            },
        )
        == 1
    )


async def test_a_missing_fallback_is_counted_as_a_failure(
    observability: ObservabilityHarness,
) -> None:
    pipeline = make_pipeline(
        primary=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason="timeout",
            )
        ),
        fallback=None,
    )

    with (
        ingestion_job_context(job_type="ingestion.process", language_code="en"),
        pytest.raises(ExtractionFailed),
    ):
        await pipeline.extract(artifact=make_artifact())

    assert (
        observability.metrics.counter_value(
            MetricName.EXTRACTION_FAILURES_TOTAL,
            labels={
                LabelKey.LANGUAGE: "en",
                LabelKey.ERROR_CODE: "other",
                LabelKey.RETRYABLE: "true",
            },
        )
        == 1
    )


async def test_extracted_text_never_reaches_span_attributes(
    observability: ObservabilityHarness,
) -> None:
    pipeline = make_pipeline(primary=FakeExtractor(text=_ARABIC_TEXT, blocks=4))

    with ingestion_job_context(job_type="ingestion.process", language_code="ar"):
        await pipeline.extract(artifact=make_artifact())

    for span in observability.tracer.spans:
        serialized = "".join(f"{key}{value}" for key, value in span.attributes.items())
        assert _ARABIC_TEXT not in serialized


async def test_arabic_and_english_are_separable_series(
    observability: ObservabilityHarness,
) -> None:
    pipeline = make_pipeline(primary=FakeExtractor(blocks=2))

    with ingestion_job_context(job_type="ingestion.process", language_code="ar"):
        await pipeline.extract(artifact=make_artifact())
    with ingestion_job_context(job_type="ingestion.process", language_code="en"):
        await pipeline.extract(artifact=make_artifact())
        await pipeline.extract(artifact=make_artifact())

    method = ExtractionMethod.OPENAI_OCR.value
    arabic = observability.metrics.counter_value(
        MetricName.EXTRACTION_PRIMARY_SUCCESS_TOTAL,
        labels={LabelKey.LANGUAGE: "ar", LabelKey.EXTRACTOR_METHOD: method},
    )
    english = observability.metrics.counter_value(
        MetricName.EXTRACTION_PRIMARY_SUCCESS_TOTAL,
        labels={LabelKey.LANGUAGE: "en", LabelKey.EXTRACTOR_METHOD: method},
    )

    assert (arabic, english) == (1, 2)
