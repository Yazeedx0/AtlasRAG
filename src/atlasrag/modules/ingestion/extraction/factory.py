from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.extraction import DocumentExtractor
from atlasrag.platform.ai.extraction import create_ocr_extractor, create_vlm_extractor

from .pipeline import ExtractionPipeline
from .quality import ShadowExtractionQualityGate


def create_extraction_pipeline(settings: Settings) -> ExtractionPipeline:
    fallback: DocumentExtractor | None = None
    if settings.GEMINI_API_KEY:
        fallback = create_vlm_extractor(settings)

    return ExtractionPipeline(
        primary=create_ocr_extractor(settings),
        fallback=fallback,
        quality_gate=ShadowExtractionQualityGate(),
    )


__all__ = ["create_extraction_pipeline"]
