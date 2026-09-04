from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from apps.api.dependencies.identity import get_local_principal_id
from apps.api.dependencies.knowledge import (
    get_document_artifact_max_file_size_bytes,
    get_document_artifact_upload_service,
)
from apps.api.dependencies.permissions import get_permission_authorization_service
from apps.api.router import api_router
from apps.api.utilities.exception_handlers import register_exception_handlers
from atlasrag.contracts.documents import UploadDocumentArtifact, UploadedDocumentArtifact
from atlasrag.contracts.error.document_errors import (
    DocumentArtifactConflict,
    DocumentArtifactContentTypeInvalid,
    DocumentArtifactTooLarge,
    DocumentNotFound,
)
from atlasrag.contracts.error.permission_errors import PermissionDenied
from atlasrag.contracts.permissions import Permission

_DOCUMENT_ID = uuid4()
_VERSION_ID = uuid4()
_ACTOR_ID = uuid4()


class FakePermissionAuthorizationService:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[tuple[UUID, Permission]] = []

    async def require(
        self,
        *,
        user_principal_id: UUID,
        permission: Permission,
    ) -> None:
        self.calls.append((user_principal_id, permission))
        if not self.allowed:
            raise PermissionDenied(
                actor_principal_id=user_principal_id,
                permission=permission,
            )


class FakeDocumentArtifactUploadService:
    def __init__(
        self,
        *,
        result: UploadedDocumentArtifact | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or UploadedDocumentArtifact(
            artifact_id=uuid4(),
            document_version_id=_VERSION_ID,
            artifact_key="primary-source",
            language_code="en",
            mime_type="text/plain",
            file_hash="a" * 64,
            file_size_bytes=11,
        )
        self.error = error
        self.calls: list[tuple[UploadDocumentArtifact, UUID]] = []

    async def upload(
        self,
        command: UploadDocumentArtifact,
        *,
        actor_principal_id: UUID,
    ) -> UploadedDocumentArtifact:
        self.calls.append((command, actor_principal_id))
        if self.error is not None:
            raise self.error
        return self.result


def make_app(
    *,
    service: FakeDocumentArtifactUploadService | None = None,
    permission_allowed: bool = True,
    max_file_size_bytes: int = 50,
) -> tuple[
    FastAPI,
    FakePermissionAuthorizationService,
    FakeDocumentArtifactUploadService,
]:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(api_router)

    authorization = FakePermissionAuthorizationService(allowed=permission_allowed)
    upload_service = service or FakeDocumentArtifactUploadService()
    application.dependency_overrides[get_local_principal_id] = lambda: _ACTOR_ID
    application.dependency_overrides[
        get_permission_authorization_service
    ] = lambda: authorization
    application.dependency_overrides[
        get_document_artifact_upload_service
    ] = lambda: upload_service
    application.dependency_overrides[
        get_document_artifact_max_file_size_bytes
    ] = lambda: max_file_size_bytes
    return application, authorization, upload_service


@pytest.mark.asyncio
async def test_upload_artifact_endpoint_builds_command_and_returns_metadata() -> None:
    service = FakeDocumentArtifactUploadService()
    application, authorization, service = make_app(service=service)
    content = b"hello atlas"
    source_updated_at = "2026-08-30T10:00:00+00:00"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/documents/{_DOCUMENT_ID}/versions/{_VERSION_ID}/artifacts",
            data={
                "artifact_key": "primary-source",
                "language_code": "en",
                "source_uri": "https://example.test/source.txt",
                "source_updated_at": source_updated_at,
            },
            files={"file": ("source.txt", content, "text/plain")},
        )

    assert response.status_code == 201
    assert response.json() == {
        "artifact_id": str(service.result.artifact_id),
        "document_version_id": str(_VERSION_ID),
        "artifact_key": "primary-source",
        "language_code": "en",
        "mime_type": "text/plain",
        "file_hash": "a" * 64,
        "file_size_bytes": 11,
    }
    assert authorization.calls == [
        (_ACTOR_ID, Permission.KNOWLEDGE_DOCUMENTS_MANAGE),
    ]
    assert len(service.calls) == 1
    command, actor_id = service.calls[0]
    assert command.document_id == _DOCUMENT_ID
    assert command.document_version_id == _VERSION_ID
    assert command.artifact_key == "primary-source"
    assert command.language_code == "en"
    assert command.source_name == "source.txt"
    assert command.source_uri == "https://example.test/source.txt"
    assert command.content_type == "text/plain"
    assert command.content == content
    assert command.source_updated_at == datetime(2026, 8, 30, 10, tzinfo=UTC)
    assert actor_id == _ACTOR_ID


@pytest.mark.asyncio
async def test_upload_artifact_endpoint_requires_manage_permission() -> None:
    application, authorization, service = make_app(permission_allowed=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/documents/{_DOCUMENT_ID}/versions/{_VERSION_ID}/artifacts",
            data={"artifact_key": "primary-source", "language_code": "en"},
            files={"file": ("source.txt", b"content", "text/plain")},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions"}
    assert authorization.calls == [
        (_ACTOR_ID, Permission.KNOWLEDGE_DOCUMENTS_MANAGE),
    ]
    assert service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (DocumentNotFound(document_id=_DOCUMENT_ID), 404),
        (
            DocumentArtifactConflict(
                document_version_id=_VERSION_ID,
                artifact_key="primary-source",
            ),
            409,
        ),
        (DocumentArtifactTooLarge(file_size_bytes=51, max_file_size_bytes=50), 413),
        (DocumentArtifactContentTypeInvalid(content_type="application/json"), 422),
    ],
)
async def test_upload_artifact_endpoint_maps_domain_errors(
    error: Exception,
    expected_status: int,
) -> None:
    application, _, service = make_app(
        service=FakeDocumentArtifactUploadService(error=error),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/documents/{_DOCUMENT_ID}/versions/{_VERSION_ID}/artifacts",
            data={"artifact_key": "primary-source", "language_code": "en"},
            files={"file": ("source.txt", b"content", "text/plain")},
        )

    assert response.status_code == expected_status
    assert response.json() == {"detail": str(error)}
    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_upload_artifact_endpoint_rejects_missing_filename() -> None:
    application, _, service = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/documents/{_DOCUMENT_ID}/versions/{_VERSION_ID}/artifacts",
            data={"artifact_key": "primary-source", "language_code": "en"},
            files={"file": ("", b"content", "text/plain")},
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "file"]
    assert service.calls == []


@pytest.mark.asyncio
async def test_upload_artifact_endpoint_rejects_naive_source_timestamp() -> None:
    application, _, service = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/documents/{_DOCUMENT_ID}/versions/{_VERSION_ID}/artifacts",
            data={
                "artifact_key": "primary-source",
                "language_code": "en",
                "source_updated_at": "2026-08-30T10:00:00",
            },
            files={"file": ("source.txt", b"content", "text/plain")},
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "source_updated_at must include a timezone offset"
    }
    assert service.calls == []
