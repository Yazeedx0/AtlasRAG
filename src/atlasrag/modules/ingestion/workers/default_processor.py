from uuid import UUID

from atlasrag.contracts.error.extraction_errors import ExtractionFailed
from atlasrag.contracts.error.object_storage_errors import (
    ObjectNotFound,
    ObjectStorageUnavailable,
)
from atlasrag.contracts.types.extraction import ExtractionResult
from atlasrag.contracts.types.ingestion import ClaimedIngestionItem, LoadedArtifact
from atlasrag.modules.ingestion.extraction.pipeline import ExtractionPipeline
from atlasrag.modules.ingestion.services.artifact_loader import (
    ArtifactIntegrityMismatch,
    ArtifactLoader,
    ArtifactUnavailableForIngestion,
)
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.workers.errors import (
    IngestionLeaseLost,
    PermanentIngestionError,
    TransientIngestionError,
)

EXTRACTION_FAILED = "extraction_failed"


def build_execution_metadata(result: ExtractionResult) -> dict[str, object]:
    return {
        "extraction": {
            "method": result.method.value,
            "fallback_used": result.fallback_used,
            "fallback_reason": result.fallback_reason,
            "quality_score": result.quality_score,
            "block_count": len(result.document.blocks),
            "document_metadata": dict(result.document.metadata),
        }
    }


class DefaultIngestionProcessor:
    def __init__(
        self,
        *,
        artifact_loader: ArtifactLoader,
        extraction_pipeline: ExtractionPipeline,
        lifecycle: IngestionLifecycleService,
    ) -> None:
        self._artifact_loader = artifact_loader
        self._extraction_pipeline = extraction_pipeline
        self._lifecycle = lifecycle

    async def process(self, *, claim: ClaimedIngestionItem) -> None:
        artifact = await self._load(artifact_id=claim.document_artifact_id)
        result = await self._extract(artifact=artifact)
        completed = await self._lifecycle.mark_completed(
            item_id=claim.ingestion_item_id,
            attempt_number=claim.attempt_number,
            observed_file_hash=artifact.observed_file_hash,
            execution_metadata=build_execution_metadata(result),
        )
        if not completed:
            raise IngestionLeaseLost("Ingestion lease was lost before completion.")

    async def _load(self, *, artifact_id: UUID) -> LoadedArtifact:
        try:
            return await self._artifact_loader.load(artifact_id=artifact_id)
        except ArtifactUnavailableForIngestion as error:
            raise PermanentIngestionError(
                error_code="artifact_unavailable_for_ingestion",
            ) from error
        except ArtifactIntegrityMismatch as error:
            raise PermanentIngestionError(
                error_code="artifact_integrity_mismatch",
            ) from error
        except ObjectNotFound as error:
            raise PermanentIngestionError(
                error_code="artifact_object_missing",
            ) from error
        except ObjectStorageUnavailable as error:
            raise TransientIngestionError("Object storage is temporarily unavailable.") from error

    async def _extract(self, *, artifact: LoadedArtifact) -> ExtractionResult:
        try:
            return await self._extraction_pipeline.extract(artifact=artifact)
        except ExtractionFailed as error:
            if error.retryable:
                raise TransientIngestionError(
                    "Document extraction failed on every provider."
                ) from error
            raise PermanentIngestionError(error_code=EXTRACTION_FAILED) from error


__all__ = [
    "EXTRACTION_FAILED",
    "DefaultIngestionProcessor",
    "build_execution_metadata",
]
