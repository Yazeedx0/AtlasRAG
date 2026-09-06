from dataclasses import dataclass
from uuid import UUID

from atlasrag.contracts.types.extraction import ExtractionResult
from atlasrag.contracts.types.ingestion import LoadedArtifact
from atlasrag.modules.ingestion.extraction.pipeline import ExtractionPipeline
from atlasrag.modules.ingestion.services.artifact_loader import ArtifactLoader


@dataclass(frozen=True, slots=True)
class ArtifactExtraction:
    artifact: LoadedArtifact
    result: ExtractionResult


class ArtifactExtractionService:
    def __init__(
        self,
        *,
        artifact_loader: ArtifactLoader,
        extraction_pipeline: ExtractionPipeline,
    ) -> None:
        self._artifact_loader = artifact_loader
        self._extraction_pipeline = extraction_pipeline

    async def extract(
        self,
        *,
        artifact_id: UUID,
        language_code: str | None = None,
    ) -> ArtifactExtraction:
        artifact = await self._artifact_loader.load(artifact_id=artifact_id)
        result = await self._extraction_pipeline.extract(
            artifact=artifact,
            language_code=language_code,
        )
        return ArtifactExtraction(artifact=artifact, result=result)


__all__ = ["ArtifactExtraction", "ArtifactExtractionService"]
