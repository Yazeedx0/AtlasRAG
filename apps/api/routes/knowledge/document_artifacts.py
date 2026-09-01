from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from apps.api.dependencies.knowledge import (
    get_document_artifact_max_file_size_bytes,
    get_document_artifact_query_service,
    get_document_artifact_upload_service,
)
from apps.api.dependencies.permissions import require_permission
from apps.api.schemas.knowledge.document_artifacts import (
    DocumentArtifactResponse,
    DocumentArtifactUploadResponse,
)
from atlasrag.contracts.documents import (
    DocumentArtifactState,
    UploadDocumentArtifact,
    UploadedDocumentArtifact,
)
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.knowledge.services.document_artifact_query import (
    DocumentArtifactQueryService,
)
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


def _to_artifact_response(artifact: DocumentArtifactState) -> DocumentArtifactResponse:
    return DocumentArtifactResponse(
        artifact_id=artifact.artifact_id,
        document_version_id=artifact.document_version_id,
        artifact_key=artifact.artifact_key,
        language_code=artifact.language_code,
        source_name=artifact.source_name,
        source_uri=artifact.source_uri,
        source_updated_at=artifact.source_updated_at,
        storage_provider=artifact.storage_provider,
        mime_type=artifact.mime_type,
        file_hash=artifact.file_hash,
        file_size_bytes=artifact.file_size_bytes,
        status=artifact.status,
        metadata=artifact.metadata,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
        retired_at=artifact.retired_at,
        deleted_at=artifact.deleted_at,
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


@router.get(
    "",
    response_model=list[DocumentArtifactResponse],
    status_code=status.HTTP_200_OK,
)
async def list_document_artifacts(
    document_id: UUID,
    version_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentArtifactQueryService,
        Depends(get_document_artifact_query_service),
    ],
) -> list[DocumentArtifactResponse]:
    artifacts = await service.list_artifacts(
        document_id=document_id,
        document_version_id=version_id,
    )
    return [_to_artifact_response(artifact) for artifact in artifacts]


@router.get(
    "/{artifact_id}",
    response_model=DocumentArtifactResponse,
    status_code=status.HTTP_200_OK,
)
async def get_document_artifact(
    document_id: UUID,
    version_id: UUID,
    artifact_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentArtifactQueryService,
        Depends(get_document_artifact_query_service),
    ],
) -> DocumentArtifactResponse:
    artifact = await service.get_artifact(
        document_id=document_id,
        document_version_id=version_id,
        artifact_id=artifact_id,
    )
    return _to_artifact_response(artifact)


__all__ = ["router"]
