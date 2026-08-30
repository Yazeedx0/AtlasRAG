from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentArtifactUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    document_version_id: UUID
    artifact_key: str
    language_code: str
    mime_type: str
    file_hash: str
    file_size_bytes: int


__all__ = ["DocumentArtifactUploadResponse"]
