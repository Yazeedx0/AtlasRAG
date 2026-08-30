from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from apps.api.dependencies.knowledge import (
    get_document_artifact_max_file_size_bytes,
    get_document_artifact_upload_service,
)
from apps.api.dependencies.permissions import require_permission
from apps.api.schemas.knowledge.document_artifacts import DocumentArtifactUploadResponse
from atlasrag.contracts.documents import UploadDocumentArtifact, UploadedDocumentArtifact
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.knowledge.services.document_artifact_upload import (
    DocumentArtifactUploadService,
)

router = APIRouter(
    prefix="/documents/{document_id}/versions/{version_id}/artifacts",
    tags=["document-artifacts"],
)


def _to_upload_response(result: UploadedDocumentArtifact) -> DocumentArtifactUploadResponse:
    return DocumentArtifactUploadResponse(
        artifact_id=result.artifact_id,
        document_version_id=result.document_version_id,
        artifact_key=result.artifact_key,
        language_code=result.language_code,
        mime_type=result.mime_type,
        file_hash=result.file_hash,
        file_size_bytes=result.file_size_bytes,
    )


@router.post(
    "",
    response_model=DocumentArtifactUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_artifact(
    document_id: UUID,
    version_id: UUID,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentArtifactUploadService,
        Depends(get_document_artifact_upload_service),
    ],
    max_file_size_bytes: Annotated[
        int,
        Depends(get_document_artifact_max_file_size_bytes),
    ],
    artifact_key: Annotated[str, Form(min_length=1)],
    language_code: Annotated[str, Form(min_length=1)],
    file: Annotated[UploadFile, File(...)],
    source_uri: Annotated[str | None, Form()] = None,
    source_updated_at: Annotated[datetime | None, Form()] = None,
) -> DocumentArtifactUploadResponse:
    if file.filename is None or not file.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="uploaded file must have a filename",
        )
    if source_updated_at is not None and source_updated_at.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="source_updated_at must include a timezone offset",
        )

    content = await file.read(max_file_size_bytes + 1)
    result = await service.upload(
        UploadDocumentArtifact(
            document_id=document_id,
            document_version_id=version_id,
            artifact_key=artifact_key,
            language_code=language_code,
            source_name=file.filename,
            source_uri=source_uri,
            content_type=file.content_type or "",
            content=content,
            source_updated_at=source_updated_at,
        ),
        actor_principal_id=actor_principal_id,
    )
    return _to_upload_response(result)


__all__ = ["router"]
