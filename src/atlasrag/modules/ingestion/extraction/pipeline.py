from atlasrag.contracts.error.extraction_errors import (
    ExtractionFailed,
    ExtractionProviderPermanentError,
    ExtractionProviderTransientError,
)
from atlasrag.contracts.extraction import DocumentExtractor, ExtractionQualityGate
from atlasrag.contracts.types.extraction import (
    ExtractedDocument,
    ExtractionMethod,
    ExtractionResult,
)
from atlasrag.contracts.types.ingestion import LoadedArtifact
from atlasrag.contracts.types.observability import (
    JobStage,
    LabelKey,
    MetricName,
    SpanName,
)
from atlasrag.platform.observability import (
    StageObservation,
    annotate_span,
    record_blocks_per_document,
    record_extraction_failure,
    record_extraction_fallback,
    record_extraction_primary_success,
    traced_stage,
    traced_stage_sync,
    update_job_context,
)

NO_FALLBACK_CONFIGURED = "no_fallback_configured"


class ExtractionPipeline:
    def __init__(
        self,
        *,
        primary: DocumentExtractor,
        fallback: DocumentExtractor | None,
        quality_gate: ExtractionQualityGate,
        primary_method: ExtractionMethod = ExtractionMethod.OPENAI_OCR,
        fallback_method: ExtractionMethod = ExtractionMethod.VLM,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._quality_gate = quality_gate
        self._primary_method = primary_method
        self._fallback_method = fallback_method

    async def extract(
        self,
        *,
        artifact: LoadedArtifact,
        language_code: str | None = None,
    ) -> ExtractionResult:
        if language_code is not None:
            update_job_context(language_code=language_code)

        async with traced_stage(
            SpanName.EXTRACTION,
            stage=JobStage.EXTRACTION,
            duration_metric=MetricName.EXTRACTION_DURATION_SECONDS,
            labels={LabelKey.EXTRACTOR_METHOD: self._primary_method.value},
        ) as observation:
            try:
                async with traced_stage(
                    SpanName.EXTRACTION_PRIMARY_OCR,
                    labels={LabelKey.EXTRACTOR_METHOD: self._primary_method.value},
                ):
                    document = await self._primary.extract(artifact=artifact)
            except (
                ExtractionProviderTransientError,
                ExtractionProviderPermanentError,
            ) as primary_error:
                observation.set_label(LabelKey.EXTRACTOR_METHOD, self._fallback_method.value)
                return await self._extract_with_fallback(
                    artifact=artifact,
                    language_code=language_code,
                    primary_error=primary_error,
                    observation=observation,
                )

            record_extraction_primary_success(extractor_method=self._primary_method.value)
            result = self._build_result(
                document=document,
                method=self._primary_method,
                language_code=language_code,
                fallback_used=False,
                fallback_reason=None,
            )
            _annotate_result(observation=observation, result=result)
            record_blocks_per_document(
                block_count=len(result.document.blocks),
                extractor_method=result.method.value,
            )
            return result

    async def _extract_with_fallback(
        self,
        *,
        artifact: LoadedArtifact,
        language_code: str | None,
        primary_error: ExtractionProviderTransientError | ExtractionProviderPermanentError,
        observation: StageObservation,
    ) -> ExtractionResult:
        if self._fallback is None:
            record_extraction_failure(
                error_code=NO_FALLBACK_CONFIGURED,
                retryable=isinstance(primary_error, ExtractionProviderTransientError),
            )
            raise ExtractionFailed(
                primary_reason=primary_error.reason,
                fallback_reason=NO_FALLBACK_CONFIGURED,
                retryable=isinstance(primary_error, ExtractionProviderTransientError),
            ) from primary_error

        try:
            async with traced_stage(
                SpanName.EXTRACTION_FALLBACK_VLM,
                labels={LabelKey.EXTRACTOR_METHOD: self._fallback_method.value},
            ):
                document = await self._fallback.extract(artifact=artifact)
        except ExtractionProviderTransientError as fallback_error:
            record_extraction_failure(error_code=fallback_error.reason, retryable=True)
            raise ExtractionFailed(
                primary_reason=primary_error.reason,
                fallback_reason=fallback_error.reason,
                retryable=True,
            ) from fallback_error
        except ExtractionProviderPermanentError as fallback_error:
            record_extraction_failure(error_code=fallback_error.reason, retryable=False)
            raise ExtractionFailed(
                primary_reason=primary_error.reason,
                fallback_reason=fallback_error.reason,
                retryable=False,
            ) from fallback_error

        record_extraction_fallback(
            extractor_method=self._fallback_method.value,
            fallback_reason=primary_error.reason,
        )
        result = self._build_result(
            document=document,
            method=self._fallback_method,
            language_code=language_code,
            fallback_used=True,
            fallback_reason=primary_error.reason,
        )
        _annotate_result(observation=observation, result=result)
        record_blocks_per_document(
            block_count=len(result.document.blocks),
            extractor_method=result.method.value,
        )
        return result

    def _build_result(
        self,
        *,
        document: ExtractedDocument,
        method: ExtractionMethod,
        language_code: str | None,
        fallback_used: bool,
        fallback_reason: str | None,
    ) -> ExtractionResult:
        with traced_stage_sync(
            SpanName.EXTRACTION_QUALITY_GATE,
            stage=JobStage.QUALITY_GATE,
        ) as observation:
            assessment = self._quality_gate.evaluate(
                document=document,
                language_code=language_code,
            )
            annotate_span(
                observation.span,
                quality_score=assessment.score,
                quality_reason_codes=",".join(assessment.reason_codes),
            )
        return ExtractionResult(
            document=document,
            method=method,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            quality_score=assessment.score,
        )


def _annotate_result(*, observation: StageObservation, result: ExtractionResult) -> None:
    annotate_span(
        observation.span,
        extractor_method=result.method.value,
        fallback_used=result.fallback_used,
        block_count=len(result.document.blocks),
        quality_score=result.quality_score if result.quality_score is not None else -1.0,
    )
    return None


__all__ = ["NO_FALLBACK_CONFIGURED", "ExtractionPipeline"]
