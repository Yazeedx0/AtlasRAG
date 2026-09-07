from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from apps.api.dependencies.ingestion import (
    get_artifact_extraction_service,
    get_ingestion_lifecycle_service,
    get_ingestion_pipeline_service,
)
from apps.api.dependencies.knowledge import get_document_artifact_max_file_size_bytes
from apps.api.dependencies.permissions import require_permission
from apps.api.schemas.ingestion.extraction import (
    ArtifactExtractionResponse,
    ExtractedBlockResponse,
    ExtractedDocumentResponse,
    IngestionItemStatusResponse,
    QueuedIngestionResponse,
)
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.ingestion.services.artifact_extraction import (
    ArtifactExtraction,
    ArtifactExtractionService,
)
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.services.ingestion_pipeline import (
    DEFAULT_ARTIFACT_KEY,
    DEFAULT_VERSION_LABEL,
    IngestDocument,
    IngestionPipelineService,
    QueuedIngestion,
)

router = APIRouter(prefix="/ingestion", tags=["ingestion-extraction"])


def _to_document_response(extraction: ArtifactExtraction) -> tuple[
    ExtractedDocumentResponse,
    int,
]:
    blocks = [
        ExtractedBlockResponse(
            text=block.text,
            block_type=block.block_type,
            page_number=block.page_number,
        )
        for block in extraction.result.document.blocks
    ]
    return (
        ExtractedDocumentResponse(
            blocks=blocks,
            metadata=dict(extraction.result.document.metadata),
        ),
        len(blocks),
    )


def _to_queued_response(queued: QueuedIngestion) -> QueuedIngestionResponse:
    return QueuedIngestionResponse(
        document_id=queued.document_id,
        document_version_id=queued.document_version_id,
        artifact_id=queued.artifact_id,
        canonical_key=queued.canonical_key,
        ingestion_run_id=queued.ingestion_run_id,
        ingestion_item_id=queued.ingestion_item_id,
        status=queued.status,
    )


def _to_response(extraction: ArtifactExtraction) -> ArtifactExtractionResponse:
    artifact = extraction.artifact
    result = extraction.result
    document, block_count = _to_document_response(extraction)
    return ArtifactExtractionResponse(
        artifact_id=artifact.artifact_id,
        mime_type=artifact.mime_type,
        file_hash=artifact.observed_file_hash,
        file_size_bytes=artifact.file_size_bytes,
        method=result.method,
        fallback_used=result.fallback_used,
        fallback_reason=result.fallback_reason,
        quality_score=result.quality_score,
        block_count=block_count,
        document=document,
    )


@router.post(
    "/artifacts/{artifact_id}/extraction",
    response_model=ArtifactExtractionResponse,
    status_code=status.HTTP_200_OK,
)
async def extract_document_artifact(
    artifact_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        ArtifactExtractionService,
        Depends(get_artifact_extraction_service),
    ],
    language_code: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
) -> ArtifactExtractionResponse:
    extraction = await service.extract(
        artifact_id=artifact_id,
        language_code=language_code,
    )
    return _to_response(extraction)


@router.post(
    "/pipeline",
    response_model=QueuedIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_ingestion_pipeline(
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        IngestionPipelineService,
        Depends(get_ingestion_pipeline_service),
    ],
    max_file_size_bytes: Annotated[
        int,
        Depends(get_document_artifact_max_file_size_bytes),
    ],
    language_code: Annotated[str, Form(min_length=1)],
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str | None, Form()] = None,
    canonical_key: Annotated[str | None, Form()] = None,
    version_label: Annotated[str, Form(min_length=1)] = DEFAULT_VERSION_LABEL,
    artifact_key: Annotated[str, Form(min_length=1)] = DEFAULT_ARTIFACT_KEY,
) -> QueuedIngestionResponse:
    if file.filename is None or not file.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="uploaded file must have a filename",
        )

    content = await file.read(max_file_size_bytes + 1)
    queued = await service.ingest(
        IngestDocument(
            title=title or file.filename,
            source_name=file.filename,
            content_type=file.content_type or "",
            content=content,
            language_code=language_code,
            canonical_key=canonical_key,
            version_label=version_label,
            artifact_key=artifact_key,
        ),
        actor_principal_id=actor_principal_id,
    )
    return _to_queued_response(queued)


@router.get(
    "/items/{ingestion_item_id}",
    response_model=IngestionItemStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_ingestion_item(
    ingestion_item_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    lifecycle: Annotated[
        IngestionLifecycleService,
        Depends(get_ingestion_lifecycle_service),
    ],
) -> IngestionItemStatusResponse:
    item = await lifecycle.find_item(item_id=ingestion_item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ingestion item {ingestion_item_id} was not found.",
        )

    return IngestionItemStatusResponse(
        ingestion_item_id=item.id,
        ingestion_run_id=item.ingestion_run_id,
        document_artifact_id=item.document_artifact_id,
        status=item.status,
        attempt_count=item.attempt_count,
        observed_file_hash=item.observed_file_hash,
        execution_metadata=item.execution_metadata,
        error_code=item.error_code,
        error_message=item.error_message,
        started_at=item.started_at,
        completed_at=item.completed_at,
    )


__all__ = ["router"]
