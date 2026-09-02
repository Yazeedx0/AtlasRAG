from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from atlasrag.contracts.types.authorization import DocumentArtifactStatus


class DocumentArtifactUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    document_version_id: UUID
    artifact_key: str
    language_code: str
    mime_type: str
    file_hash: str
    file_size_bytes: int


class DocumentArtifactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    document_version_id: UUID
    artifact_key: str
    language_code: str
    source_name: str
    source_uri: str | None
    source_updated_at: datetime | None
    storage_provider: str
    mime_type: str
    file_hash: str
    file_size_bytes: int
    status: DocumentArtifactStatus
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
    retired_at: datetime | None
    deleted_at: datetime | None


__all__ = ["DocumentArtifactResponse", "DocumentArtifactUploadResponse"]
