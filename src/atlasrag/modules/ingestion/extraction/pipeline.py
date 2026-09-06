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


class ExtractionPipeline:
    def __init__(
        self,
        *,
        primary: DocumentExtractor,
        fallback: DocumentExtractor,
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
        try:
            document = await self._primary.extract(artifact=artifact)
        except (
            ExtractionProviderTransientError,
            ExtractionProviderPermanentError,
        ) as primary_error:
            return await self._extract_with_fallback(
                artifact=artifact,
                language_code=language_code,
                primary_error=primary_error,
            )

        return self._build_result(
            document=document,
            method=self._primary_method,
            language_code=language_code,
            fallback_used=False,
            fallback_reason=None,
        )

    async def _extract_with_fallback(
        self,
        *,
        artifact: LoadedArtifact,
        language_code: str | None,
        primary_error: ExtractionProviderTransientError | ExtractionProviderPermanentError,
    ) -> ExtractionResult:
        try:
            document = await self._fallback.extract(artifact=artifact)
        except ExtractionProviderTransientError as fallback_error:
            raise ExtractionFailed(
                primary_reason=primary_error.reason,
                fallback_reason=fallback_error.reason,
                retryable=True,
            ) from fallback_error
        except ExtractionProviderPermanentError as fallback_error:
            raise ExtractionFailed(
                primary_reason=primary_error.reason,
                fallback_reason=fallback_error.reason,
                retryable=False,
            ) from fallback_error

        return self._build_result(
            document=document,
            method=self._fallback_method,
            language_code=language_code,
            fallback_used=True,
            fallback_reason=primary_error.reason,
        )

    def _build_result(
        self,
        *,
        document: ExtractedDocument,
        method: ExtractionMethod,
        language_code: str | None,
        fallback_used: bool,
        fallback_reason: str | None,
    ) -> ExtractionResult:
        assessment = self._quality_gate.evaluate(
            document=document,
            language_code=language_code,
        )
        return ExtractionResult(
            document=document,
            method=method,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            quality_score=assessment.score,
        )


__all__ = ["ExtractionPipeline"]
