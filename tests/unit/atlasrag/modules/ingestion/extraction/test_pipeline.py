import hashlib
from uuid import uuid4

import pytest

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
from atlasrag.modules.ingestion.extraction.pipeline import ExtractionPipeline

PRIMARY_TEXT = "primary extractor output"
FALLBACK_TEXT = "fallback extractor output"


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


def make_document(text: str) -> ExtractedDocument:
    return ExtractedDocument(
        blocks=(
            ExtractedBlock(
                text=text,
                block_type=ExtractedBlockType.PARAGRAPH,
                page_number=1,
            ),
        )
    )


class FakeExtractor:
    def __init__(self, *, text: str = PRIMARY_TEXT, error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[LoadedArtifact] = []

    async def extract(self, *, artifact: LoadedArtifact) -> ExtractedDocument:
        self.calls.append(artifact)
        if self._error is not None:
            raise self._error
        return make_document(self._text)


class FakeQualityGate:
    def __init__(self, *, score: float = 0.1) -> None:
        self._score = score
        self.calls: list[tuple[ExtractedDocument, str | None]] = []

    def evaluate(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None,
    ) -> ExtractionQualityAssessment:
        self.calls.append((document, language_code))
        return ExtractionQualityAssessment(score=self._score, reason_codes=("shadow",))


def make_pipeline(
    *,
    primary: FakeExtractor,
    fallback: FakeExtractor,
    quality_gate: FakeQualityGate,
) -> ExtractionPipeline:
    return ExtractionPipeline(
        primary=primary,
        fallback=fallback,
        quality_gate=quality_gate,
    )


@pytest.mark.asyncio
async def test_primary_success_does_not_invoke_fallback() -> None:
    primary = FakeExtractor()
    fallback = FakeExtractor(text=FALLBACK_TEXT)
    artifact = make_artifact()
    pipeline = make_pipeline(
        primary=primary,
        fallback=fallback,
        quality_gate=FakeQualityGate(),
    )

    result = await pipeline.extract(artifact=artifact)

    assert primary.calls == [artifact]
    assert fallback.calls == []
    assert result.method is ExtractionMethod.OPENAI_OCR
    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert result.document.blocks[0].text == PRIMARY_TEXT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "primary_error",
    [
        ExtractionProviderTransientError(
            method=ExtractionMethod.OPENAI_OCR,
            reason="timeout",
        ),
        ExtractionProviderPermanentError(
            method=ExtractionMethod.OPENAI_OCR,
            reason="malformed_provider_response",
        ),
    ],
)
async def test_technical_primary_failure_falls_back_and_records_reason(
    primary_error: Exception,
) -> None:
    fallback = FakeExtractor(text=FALLBACK_TEXT)
    artifact = make_artifact()
    pipeline = make_pipeline(
        primary=FakeExtractor(error=primary_error),
        fallback=fallback,
        quality_gate=FakeQualityGate(),
    )

    result = await pipeline.extract(artifact=artifact)

    assert fallback.calls == [artifact]
    assert result.method is ExtractionMethod.VLM
    assert result.fallback_used is True
    assert result.fallback_reason == primary_error.reason
    assert result.document.blocks[0].text == FALLBACK_TEXT


@pytest.mark.asyncio
async def test_quality_gate_is_evaluated_on_primary_output() -> None:
    quality_gate = FakeQualityGate(score=0.42)
    pipeline = make_pipeline(
        primary=FakeExtractor(),
        fallback=FakeExtractor(text=FALLBACK_TEXT),
        quality_gate=quality_gate,
    )

    result = await pipeline.extract(artifact=make_artifact(), language_code="ar")

    assert len(quality_gate.calls) == 1
    evaluated_document, language_code = quality_gate.calls[0]
    assert evaluated_document is result.document
    assert language_code == "ar"
    assert result.quality_score == 0.42


@pytest.mark.asyncio
async def test_low_quality_score_does_not_trigger_fallback_in_shadow_mode() -> None:
    fallback = FakeExtractor(text=FALLBACK_TEXT)
    pipeline = make_pipeline(
        primary=FakeExtractor(),
        fallback=fallback,
        quality_gate=FakeQualityGate(score=0.0),
    )

    result = await pipeline.extract(artifact=make_artifact())

    assert fallback.calls == []
    assert result.method is ExtractionMethod.OPENAI_OCR
    assert result.fallback_used is False
    assert result.quality_score == 0.0


@pytest.mark.asyncio
async def test_quality_gate_is_evaluated_on_fallback_output() -> None:
    quality_gate = FakeQualityGate(score=0.7)
    pipeline = make_pipeline(
        primary=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason="timeout",
            )
        ),
        fallback=FakeExtractor(text=FALLBACK_TEXT),
        quality_gate=quality_gate,
    )

    result = await pipeline.extract(artifact=make_artifact())

    assert len(quality_gate.calls) == 1
    assert quality_gate.calls[0][0] is result.document
    assert result.quality_score == 0.7


@pytest.mark.asyncio
async def test_primary_and_transient_fallback_failure_is_retryable() -> None:
    pipeline = make_pipeline(
        primary=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason="ocr_timeout",
            )
        ),
        fallback=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.VLM,
                reason="vlm_unavailable",
            )
        ),
        quality_gate=FakeQualityGate(),
    )

    with pytest.raises(ExtractionFailed) as error:
        await pipeline.extract(artifact=make_artifact())

    assert error.value.retryable is True
    assert error.value.primary_reason == "ocr_timeout"
    assert error.value.fallback_reason == "vlm_unavailable"


@pytest.mark.asyncio
async def test_primary_and_permanent_fallback_failure_is_not_retryable() -> None:
    pipeline = make_pipeline(
        primary=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason="ocr_timeout",
            )
        ),
        fallback=FakeExtractor(
            error=ExtractionProviderPermanentError(
                method=ExtractionMethod.VLM,
                reason="unsupported_mime_type",
            )
        ),
        quality_gate=FakeQualityGate(),
    )

    with pytest.raises(ExtractionFailed) as error:
        await pipeline.extract(artifact=make_artifact())

    assert error.value.retryable is False
    assert error.value.fallback_reason == "unsupported_mime_type"


@pytest.mark.asyncio
async def test_quality_gate_is_not_evaluated_when_extraction_fails() -> None:
    quality_gate = FakeQualityGate()
    pipeline = make_pipeline(
        primary=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason="ocr_timeout",
            )
        ),
        fallback=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.VLM,
                reason="vlm_unavailable",
            )
        ),
        quality_gate=quality_gate,
    )

    with pytest.raises(ExtractionFailed):
        await pipeline.extract(artifact=make_artifact())

    assert quality_gate.calls == []


@pytest.mark.asyncio
async def test_both_extractors_produce_provider_neutral_documents() -> None:
    artifact = make_artifact()
    primary_pipeline = make_pipeline(
        primary=FakeExtractor(),
        fallback=FakeExtractor(text=FALLBACK_TEXT),
        quality_gate=FakeQualityGate(),
    )
    fallback_pipeline = make_pipeline(
        primary=FakeExtractor(
            error=ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason="timeout",
            )
        ),
        fallback=FakeExtractor(text=FALLBACK_TEXT),
        quality_gate=FakeQualityGate(),
    )

    primary_result = await primary_pipeline.extract(artifact=artifact)
    fallback_result = await fallback_pipeline.extract(artifact=artifact)

    assert type(primary_result.document) is type(fallback_result.document)
    for result in (primary_result, fallback_result):
        assert isinstance(result.document, ExtractedDocument)
        for block in result.document.blocks:
            assert isinstance(block.block_type, ExtractedBlockType)
