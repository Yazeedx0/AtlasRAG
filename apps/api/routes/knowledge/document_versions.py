from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from apps.api.dependencies.knowledge import get_document_version_management_service
from apps.api.dependencies.permissions import require_permission
from apps.api.schemas.knowledge.document_versions import (
    DocumentVersionCreateRequest,
    DocumentVersionPublishRequest,
    DocumentVersionResponse,
    DocumentVersionWithdrawRequest,
)
from atlasrag.contracts.documents import DocumentVersionState
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.knowledge.services.document_version_management import (
    DocumentVersionManagementService,
)

router = APIRouter(prefix="/documents/{document_id}/versions", tags=["document-versions"])


def _to_version_response(version: DocumentVersionState) -> DocumentVersionResponse:
    return DocumentVersionResponse(
        id=version.version_id,
        document_id=version.document_id,
        version_label=version.version_label,
        effective_from=version.effective_from,
        effective_to=version.effective_to,
        published_at=version.published_at,
        status=version.status,
        created_by_principal_id=version.created_by_principal_id,
        metadata=version.metadata,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


@router.post(
    "",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_version(
    document_id: UUID,
    payload: DocumentVersionCreateRequest,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentVersionManagementService,
        Depends(get_document_version_management_service),
    ],
) -> DocumentVersionResponse:
    version = await service.create_version(
        document_id=document_id,
        version_label=payload.version_label,
        actor_principal_id=actor_principal_id,
        metadata=payload.metadata,
    )
    return _to_version_response(version)


@router.get(
    "",
    response_model=list[DocumentVersionResponse],
    status_code=status.HTTP_200_OK,
)
async def list_document_versions(
    document_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentVersionManagementService,
        Depends(get_document_version_management_service),
    ],
) -> list[DocumentVersionResponse]:
    versions = await service.list_versions(document_id=document_id)
    return [_to_version_response(version) for version in versions]


@router.get(
    "/effective",
    response_model=DocumentVersionResponse | None,
    status_code=status.HTTP_200_OK,
)
async def get_effective_document_version(
    document_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentVersionManagementService,
        Depends(get_document_version_management_service),
    ],
    at: Annotated[datetime | None, Query()] = None,
) -> DocumentVersionResponse | None:
    version = await service.get_effective_version(document_id=document_id, at=at)
    return _to_version_response(version) if version is not None else None


@router.get(
    "/{version_id}",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_200_OK,
)
async def get_document_version(
    document_id: UUID,
    version_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentVersionManagementService,
        Depends(get_document_version_management_service),
    ],
) -> DocumentVersionResponse:
    version = await service.get_version(document_id=document_id, version_id=version_id)
    return _to_version_response(version)


@router.post(
    "/{version_id}/publish",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_200_OK,
)
async def publish_document_version(
    document_id: UUID,
    version_id: UUID,
    payload: DocumentVersionPublishRequest,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentVersionManagementService,
        Depends(get_document_version_management_service),
    ],
) -> DocumentVersionResponse:
    version = await service.publish_version(
        document_id=document_id,
        version_id=version_id,
        effective_from=payload.effective_from,
    )
    return _to_version_response(version)


@router.post(
    "/{version_id}/withdraw",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_200_OK,
)
async def withdraw_document_version(
    document_id: UUID,
    version_id: UUID,
    payload: DocumentVersionWithdrawRequest,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentVersionManagementService,
        Depends(get_document_version_management_service),
    ],
) -> DocumentVersionResponse:
    version = await service.withdraw_version(
        document_id=document_id,
        version_id=version_id,
        effective_to=payload.effective_to,
    )
    return _to_version_response(version)


@router.post(
    "/{version_id}/archive",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_200_OK,
)
async def archive_document_version(
    document_id: UUID,
    version_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentVersionManagementService,
        Depends(get_document_version_management_service),
    ],
) -> DocumentVersionResponse:
    version = await service.archive_version(document_id=document_id, version_id=version_id)
    return _to_version_response(version)
