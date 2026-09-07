from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from atlasrag.contracts.types.extraction import ExtractedBlockType, ExtractionMethod
from atlasrag.contracts.types.ingestion import IngestionStatus


class ExtractedBlockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    block_type: ExtractedBlockType
    page_number: int | None


class ExtractedDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks: list[ExtractedBlockResponse]
    metadata: dict[str, object]


class QueuedIngestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    document_version_id: UUID
    artifact_id: UUID
    canonical_key: str
    ingestion_run_id: UUID
    ingestion_item_id: UUID
    status: IngestionStatus


class IngestionItemStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingestion_item_id: UUID
    ingestion_run_id: UUID
    document_artifact_id: UUID
    status: IngestionStatus
    attempt_count: int
    observed_file_hash: str | None
    execution_metadata: dict[str, object]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


class ArtifactExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    mime_type: str
    file_hash: str
    file_size_bytes: int
    method: ExtractionMethod
    fallback_used: bool
    fallback_reason: str | None
    quality_score: float | None
    block_count: int
    document: ExtractedDocumentResponse


__all__ = [
    "ArtifactExtractionResponse",
    "ExtractedBlockResponse",
    "ExtractedDocumentResponse",
    "IngestionItemStatusResponse",
    "QueuedIngestionResponse",
]
