from typing import Protocol, runtime_checkable

from atlasrag.contracts.types.extraction import (
    ExtractedDocument,
    ExtractionQualityAssessment,
)
from atlasrag.contracts.types.ingestion import LoadedArtifact


@runtime_checkable
class DocumentExtractor(Protocol):
    async def extract(
        self,
        *,
        artifact: LoadedArtifact,
    ) -> ExtractedDocument:
        ...


@runtime_checkable
class ExtractionQualityGate(Protocol):
    def evaluate(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None,
    ) -> ExtractionQualityAssessment:
        ...


__all__ = ["DocumentExtractor", "ExtractionQualityGate"]
