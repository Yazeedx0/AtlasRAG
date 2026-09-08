from uuid import UUID

from atlasrag.contracts.error.extraction_errors import ExtractionFailed
from atlasrag.contracts.error.object_storage_errors import (
    ObjectNotFound,
    ObjectStorageUnavailable,
)
from atlasrag.contracts.types.chunking import ChunkDraft
from atlasrag.contracts.types.extraction import ExtractionResult
from atlasrag.contracts.types.ingestion import ClaimedIngestionItem, LoadedArtifact
from atlasrag.modules.ingestion.chunking import ChunkerResolver, ChunkingConfig
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
CHUNKING_FAILED = "chunking_failed"


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


def with_chunking_metadata(
    metadata: dict[str, object],
    *,
    config: ChunkingConfig,
    chunk_count: int,
) -> dict[str, object]:
    return {
        **metadata,
        "chunking": {
            "strategy": config.strategy.value,
            "reference_tokenizer": config.reference_tokenizer,
            "reference_tokenizer_version": config.reference_tokenizer_version,
            "chunk_count": chunk_count,
        },
    }


class DefaultIngestionProcessor:
    def __init__(
        self,
        *,
        artifact_loader: ArtifactLoader,
        extraction_pipeline: ExtractionPipeline,
        lifecycle: IngestionLifecycleService,
        chunker_resolver: ChunkerResolver,
    ) -> None:
        self._artifact_loader = artifact_loader
        self._extraction_pipeline = extraction_pipeline
        self._lifecycle = lifecycle
        self._chunker_resolver = chunker_resolver

    async def process(self, *, claim: ClaimedIngestionItem) -> None:
        artifact = await self._load(artifact_id=claim.document_artifact_id)
        result = await self._extract(artifact=artifact)
        config = await self._get_chunking_config(claim=claim)
        chunks = self._chunk(
            result=result,
            config=config,
            language_code=artifact.language_code,
        )
        completed = await self._lifecycle.replace_chunks_and_mark_completed(
            item_id=claim.ingestion_item_id,
            attempt_number=claim.attempt_number,
            chunks=chunks,
            observed_file_hash=artifact.observed_file_hash,
            execution_metadata=with_chunking_metadata(
                build_execution_metadata(result),
                config=config,
                chunk_count=len(chunks),
            ),
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
            return await self._extraction_pipeline.extract(
                artifact=artifact,
                language_code=artifact.language_code,
            )
        except ExtractionFailed as error:
            if error.retryable:
                raise TransientIngestionError(
                    "Document extraction failed on every provider."
                ) from error
            raise PermanentIngestionError(error_code=EXTRACTION_FAILED) from error

    async def _get_chunking_config(self, *, claim: ClaimedIngestionItem) -> ChunkingConfig:
        if claim.ingestion_run_id is None:
            raise PermanentIngestionError(error_code=CHUNKING_FAILED)
        run = await self._lifecycle.find_run(run_id=claim.ingestion_run_id)
        if run is None:
            raise PermanentIngestionError(error_code=CHUNKING_FAILED)
        try:
            return ChunkingConfig.from_run_configuration(run.configuration)
        except ValueError as error:
            raise PermanentIngestionError(error_code=CHUNKING_FAILED) from error

    def _chunk(
        self,
        *,
        result: ExtractionResult,
        config: ChunkingConfig,
        language_code: str | None,
    ) -> tuple[ChunkDraft, ...]:
        try:
            chunker = self._chunker_resolver.resolve(config=config)
            return chunker.chunk(document=result.document, language_code=language_code)
        except ValueError as error:
            raise PermanentIngestionError(error_code=CHUNKING_FAILED) from error


__all__ = [
    "CHUNKING_FAILED",
    "EXTRACTION_FAILED",
    "DefaultIngestionProcessor",
    "build_execution_metadata",
    "with_chunking_metadata",
]
