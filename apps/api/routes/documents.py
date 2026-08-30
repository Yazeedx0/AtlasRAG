from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from apps.api.dependencies.knowledge import (
    get_document_acl_management_service,
    get_document_management_service,
)
from apps.api.dependencies.permissions import require_permission
from apps.api.schemas.documents import (
    DocumentAclGrantCreateRequest,
    DocumentAclGrantResponse,
    DocumentCreateRequest,
    DocumentResponse,
    DocumentUpdateRequest,
)
from atlasrag.contracts.documents import (
    DocumentAclGrantState,
    DocumentField,
    DocumentPatch,
    DocumentState,
)
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.knowledge.services.document_acl_management import (
    DocumentAclManagementService,
)
from atlasrag.modules.knowledge.services.document_management import (
    DocumentManagementService,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _to_document_response(document: DocumentState) -> DocumentResponse:
    return DocumentResponse(
        id=document.document_id,
        created_by_principal_id=document.created_by_principal_id,
        canonical_key=document.canonical_key,
        title=document.title,
        description=document.description,
        document_type=document.document_type,
        department=document.department,
        default_language_code=document.default_language_code,
        metadata=document.metadata,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _to_acl_grant_response(grant: DocumentAclGrantState) -> DocumentAclGrantResponse:
    return DocumentAclGrantResponse(
        grant_id=grant.grant_id,
        principal_id=grant.principal_id,
        permission=grant.permission,
        granted_at=grant.granted_at,
        granted_by_principal_id=grant.granted_by_principal_id,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
        revoked_by_principal_id=grant.revoked_by_principal_id,
    )


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    payload: DocumentCreateRequest,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentManagementService,
        Depends(get_document_management_service),
    ],
) -> DocumentResponse:
    document = await service.create_document(
        canonical_key=payload.canonical_key,
        title=payload.title,
        actor_principal_id=actor_principal_id,
        description=payload.description,
        document_type=payload.document_type,
        department=payload.department,
        default_language_code=payload.default_language_code,
        metadata=payload.metadata,
    )
    return _to_document_response(document)


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
)
async def update_document(
    document_id: UUID,
    payload: DocumentUpdateRequest,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentManagementService,
        Depends(get_document_management_service),
    ],
) -> DocumentResponse:
    document = await service.update_document(
        document_id=document_id,
        patch=DocumentPatch(
            fields=frozenset(DocumentField(field) for field in payload.model_fields_set),
            title=payload.title,
            description=payload.description,
            document_type=payload.document_type,
            department=payload.department,
            default_language_code=payload.default_language_code,
            metadata=payload.metadata,
        ),
    )
    return _to_document_response(document)


@router.delete(
    "/{document_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    document_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENTS_MANAGE)),
    ],
    service: Annotated[
        DocumentManagementService,
        Depends(get_document_management_service),
    ],
) -> Response:
    await service.delete_document(document_id=document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{document_id}/acl",
    response_model=list[DocumentAclGrantResponse],
    status_code=status.HTTP_200_OK,
)
async def list_document_acl(
    document_id: UUID,
    _: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_ACL_MANAGE)),
    ],
    service: Annotated[
        DocumentAclManagementService,
        Depends(get_document_acl_management_service),
    ],
    include_history: Annotated[bool, Query()] = False,
) -> list[DocumentAclGrantResponse]:
    grants = await service.list_acl_grants(
        document_id=document_id,
        include_history=include_history,
    )
    return [_to_acl_grant_response(grant) for grant in grants]


@router.post(
    "/{document_id}/acl",
    response_model=DocumentAclGrantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def grant_document_acl(
    document_id: UUID,
    payload: DocumentAclGrantCreateRequest,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_ACL_MANAGE)),
    ],
    service: Annotated[
        DocumentAclManagementService,
        Depends(get_document_acl_management_service),
    ],
) -> DocumentAclGrantResponse:
    grant = await service.grant_acl(
        document_id=document_id,
        principal_id=payload.principal_id,
        permission=payload.permission,
        expires_at=payload.expires_at,
        actor_principal_id=actor_principal_id,
    )
    return _to_acl_grant_response(grant)


@router.delete(
    "/{document_id}/acl/{grant_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_document_acl(
    document_id: UUID,
    grant_id: UUID,
    actor_principal_id: Annotated[
        UUID,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_ACL_MANAGE)),
    ],
    service: Annotated[
        DocumentAclManagementService,
        Depends(get_document_acl_management_service),
    ],
) -> Response:
    await service.revoke_acl(
        document_id=document_id,
        grant_id=grant_id,
        actor_principal_id=actor_principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
