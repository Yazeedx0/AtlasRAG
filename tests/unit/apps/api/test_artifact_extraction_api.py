import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from apps.api.dependencies.identity import get_local_principal_id
from apps.api.dependencies.ingestion import (
    get_artifact_extraction_service,
    get_ingestion_lifecycle_service,
    get_ingestion_pipeline_service,
)
from apps.api.dependencies.knowledge import get_document_artifact_max_file_size_bytes
from apps.api.dependencies.permissions import get_permission_authorization_service
from apps.api.router import api_router
from apps.api.utilities.exception_handlers import register_exception_handlers
from fastapi import FastAPI

from atlasrag.contracts.error.extraction_errors import ExtractionFailed
from atlasrag.contracts.error.object_storage_errors import ObjectNotFound
from atlasrag.contracts.error.permission_errors import PermissionDenied
from atlasrag.contracts.permissions import Permission
from atlasrag.contracts.types.authorization import DocumentArtifactStatus
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
    ExtractionMethod,
    ExtractionResult,
)
from atlasrag.contracts.types.ingestion import IngestionItemState, IngestionStatus, LoadedArtifact
from atlasrag.modules.ingestion.services.artifact_extraction import ArtifactExtraction
from atlasrag.modules.ingestion.services.artifact_loader import (
    ArtifactIntegrityMismatch,
    ArtifactUnavailableForIngestion,
)
from atlasrag.modules.ingestion.services.ingestion_pipeline import (
    IngestDocument,
    QueuedIngestion,
)

_ARTIFACT_ID = uuid4()
_ACTOR_ID = uuid4()
_CONTENT = b"AtlasRAG verified artifact"


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


def make_extraction(
    *,
    method: ExtractionMethod = ExtractionMethod.OPENAI_OCR,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
    quality_score: float | None = 0.91,
) -> ArtifactExtraction:
    digest = hashlib.sha256(_CONTENT).hexdigest()
    return ArtifactExtraction(
        artifact=LoadedArtifact(
            artifact_id=_ARTIFACT_ID,
            content=_CONTENT,
            mime_type="application/pdf",
            expected_file_hash=digest,
            observed_file_hash=digest,
            file_size_bytes=len(_CONTENT),
        ),
        result=ExtractionResult(
            document=ExtractedDocument(
                blocks=(
                    ExtractedBlock(
                        text="Annual Leave",
                        block_type=ExtractedBlockType.HEADING,
                        page_number=4,
                    ),
                    ExtractedBlock(
                        text="Employees are entitled to...",
                        block_type=ExtractedBlockType.PARAGRAPH,
                        page_number=4,
                    ),
                ),
                metadata={"model": "gpt-4o"},
            ),
            method=method,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            quality_score=quality_score,
        ),
    )


class FakeArtifactExtractionService:
    def __init__(
        self,
        *,
        extraction: ArtifactExtraction | None = None,
        error: Exception | None = None,
    ) -> None:
        self.extraction = extraction or make_extraction()
        self.error = error
        self.calls: list[tuple[UUID, str | None]] = []

    async def extract(
        self,
        *,
        artifact_id: UUID,
        language_code: str | None = None,
    ) -> ArtifactExtraction:
        self.calls.append((artifact_id, language_code))
        if self.error is not None:
            raise self.error
        return self.extraction


def make_app(
    *,
    service: FakeArtifactExtractionService | None = None,
    permission_allowed: bool = True,
) -> tuple[FastAPI, FakePermissionAuthorizationService, FakeArtifactExtractionService]:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(api_router)

    authorization = FakePermissionAuthorizationService(allowed=permission_allowed)
    extraction_service = service or FakeArtifactExtractionService()
    application.dependency_overrides[get_local_principal_id] = lambda: _ACTOR_ID
    application.dependency_overrides[
        get_permission_authorization_service
    ] = lambda: authorization
    application.dependency_overrides[
        get_artifact_extraction_service
    ] = lambda: extraction_service
    return application, authorization, extraction_service


def extraction_url(artifact_id: UUID = _ARTIFACT_ID) -> str:
    return f"/api/v1/ingestion/artifacts/{artifact_id}/extraction"


async def post_extraction(application: FastAPI, *, url: str | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        return await client.post(url or extraction_url())


@pytest.mark.asyncio
async def test_extraction_endpoint_returns_the_verified_document_and_execution_metadata() -> None:
    application, _, service = make_app()

    response = await post_extraction(application)

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"] == str(_ARTIFACT_ID)
    assert body["mime_type"] == "application/pdf"
    assert body["file_hash"] == hashlib.sha256(_CONTENT).hexdigest()
    assert body["file_size_bytes"] == len(_CONTENT)
    assert body["method"] == "openai_ocr"
    assert body["fallback_used"] is False
    assert body["fallback_reason"] is None
    assert body["quality_score"] == 0.91
    assert body["block_count"] == 2
    assert body["document"]["metadata"] == {"model": "gpt-4o"}
    assert body["document"]["blocks"][0] == {
        "text": "Annual Leave",
        "block_type": "heading",
        "page_number": 4,
    }
    assert service.calls == [(_ARTIFACT_ID, None)]


@pytest.mark.asyncio
async def test_extraction_endpoint_reports_the_fallback_that_actually_ran() -> None:
    service = FakeArtifactExtractionService(
        extraction=make_extraction(
            method=ExtractionMethod.VLM,
            fallback_used=True,
            fallback_reason="http_503",
            quality_score=None,
        )
    )
    application, _, _ = make_app(service=service)

    response = await post_extraction(application)

    body = response.json()
    assert body["method"] == "vlm"
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "http_503"
    assert body["quality_score"] is None


@pytest.mark.asyncio
async def test_extraction_endpoint_forwards_the_language_code() -> None:
    application, _, service = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(extraction_url(), params={"language_code": "ar"})

    assert response.status_code == 200
    assert service.calls == [(_ARTIFACT_ID, "ar")]


@pytest.mark.asyncio
async def test_extraction_endpoint_requires_manage_permission() -> None:
    application, authorization, service = make_app(permission_allowed=False)

    response = await post_extraction(application)

    assert response.status_code == 403
    assert authorization.calls == [(_ACTOR_ID, Permission.KNOWLEDGE_DOCUMENTS_MANAGE)]
    assert service.calls == []


@pytest.mark.asyncio
async def test_extraction_endpoint_rejects_a_malformed_artifact_id() -> None:
    application, _, service = make_app()

    response = await post_extraction(
        application,
        url="/api/v1/ingestion/artifacts/not-a-uuid/extraction",
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.asyncio
async def test_extraction_endpoint_rejects_a_blank_language_code() -> None:
    application, _, service = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(extraction_url(), params={"language_code": ""})

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            ArtifactUnavailableForIngestion(artifact_id=_ARTIFACT_ID, status=None),
            404,
        ),
        (
            ArtifactUnavailableForIngestion(
                artifact_id=_ARTIFACT_ID,
                status=DocumentArtifactStatus.RETIRED,
            ),
            404,
        ),
        (ObjectNotFound(key="documents/missing"), 404),
        (
            ArtifactIntegrityMismatch(
                artifact_id=_ARTIFACT_ID,
                expected_file_hash="a" * 64,
                observed_file_hash="b" * 64,
                expected_file_size_bytes=10,
                observed_file_size_bytes=11,
            ),
            422,
        ),
        (
            ExtractionFailed(
                primary_reason="http_500",
                fallback_reason="http_503",
                retryable=True,
            ),
            502,
        ),
        (
            ExtractionFailed(
                primary_reason="http_500",
                fallback_reason="malformed_provider_response",
                retryable=False,
            ),
            502,
        ),
    ],
)
async def test_extraction_endpoint_maps_domain_errors(
    error: Exception,
    expected_status: int,
) -> None:
    application, _, _ = make_app(service=FakeArtifactExtractionService(error=error))

    response = await post_extraction(application)

    assert response.status_code == expected_status
    assert "detail" in response.json()


_DOCUMENT_ID = uuid4()
_VERSION_ID = uuid4()
_PIPELINE_URL = "/api/v1/ingestion/pipeline"


class FakeIngestionPipelineService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[IngestDocument, UUID]] = []
        self.run_id = uuid4()
        self.item_id = uuid4()

    async def ingest(
        self,
        command: IngestDocument,
        *,
        actor_principal_id: UUID,
    ) -> QueuedIngestion:
        self.calls.append((command, actor_principal_id))
        if self.error is not None:
            raise self.error
        return QueuedIngestion(
            document_id=_DOCUMENT_ID,
            document_version_id=_VERSION_ID,
            artifact_id=_ARTIFACT_ID,
            canonical_key=command.canonical_key or "ingestion-generated",
            ingestion_run_id=self.run_id,
            ingestion_item_id=self.item_id,
            status=IngestionStatus.PENDING,
        )


def make_pipeline_app(
    *,
    service: FakeIngestionPipelineService | None = None,
    permission_allowed: bool = True,
    max_file_size_bytes: int = 1024,
) -> tuple[FastAPI, FakePermissionAuthorizationService, FakeIngestionPipelineService]:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(api_router)

    authorization = FakePermissionAuthorizationService(allowed=permission_allowed)
    pipeline_service = service or FakeIngestionPipelineService()
    application.dependency_overrides[get_local_principal_id] = lambda: _ACTOR_ID
    application.dependency_overrides[
        get_permission_authorization_service
    ] = lambda: authorization
    application.dependency_overrides[
        get_ingestion_pipeline_service
    ] = lambda: pipeline_service
    application.dependency_overrides[
        get_document_artifact_max_file_size_bytes
    ] = lambda: max_file_size_bytes
    return application, authorization, pipeline_service


async def post_pipeline(
    application: FastAPI,
    *,
    data: dict[str, str] | None = None,
    filename: str = "handbook.pdf",
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        return await client.post(
            _PIPELINE_URL,
            data=data if data is not None else {"language_code": "ar"},
            files={"file": (filename, _CONTENT, "application/pdf")},
        )


@pytest.mark.asyncio
async def test_pipeline_endpoint_creates_the_document_chain_and_returns_extraction() -> None:
    application, _, service = make_pipeline_app()

    response = await post_pipeline(application)

    assert response.status_code == 202
    body = response.json()
    assert body["document_id"] == str(_DOCUMENT_ID)
    assert body["document_version_id"] == str(_VERSION_ID)
    assert body["artifact_id"] == str(_ARTIFACT_ID)
    assert body["canonical_key"] == "ingestion-generated"
    assert body["ingestion_run_id"] == str(service.run_id)
    assert body["ingestion_item_id"] == str(service.item_id)
    assert body["status"] == "pending"

    command, actor = service.calls[0]
    assert actor == _ACTOR_ID
    assert command.source_name == "handbook.pdf"
    assert command.content == _CONTENT
    assert command.content_type == "application/pdf"
    assert command.language_code == "ar"


@pytest.mark.asyncio
async def test_pipeline_endpoint_defaults_the_title_to_the_filename() -> None:
    application, _, service = make_pipeline_app()

    await post_pipeline(application)

    assert service.calls[0][0].title == "handbook.pdf"


@pytest.mark.asyncio
async def test_pipeline_endpoint_forwards_optional_form_fields() -> None:
    application, _, service = make_pipeline_app()

    response = await post_pipeline(
        application,
        data={
            "language_code": "en",
            "title": "Employee Handbook",
            "canonical_key": "hr/handbook/2026",
            "version_label": "v2",
            "artifact_key": "scanned",
        },
    )

    assert response.status_code == 202
    command, _ = service.calls[0]
    assert command.title == "Employee Handbook"
    assert command.canonical_key == "hr/handbook/2026"
    assert command.version_label == "v2"
    assert command.artifact_key == "scanned"
    assert response.json()["canonical_key"] == "hr/handbook/2026"


@pytest.mark.asyncio
async def test_pipeline_endpoint_requires_manage_permission() -> None:
    application, authorization, service = make_pipeline_app(permission_allowed=False)

    response = await post_pipeline(application)

    assert response.status_code == 403
    assert authorization.calls == [(_ACTOR_ID, Permission.KNOWLEDGE_DOCUMENTS_MANAGE)]
    assert service.calls == []


@pytest.mark.asyncio
async def test_pipeline_endpoint_requires_a_language_code() -> None:
    application, _, service = make_pipeline_app()

    response = await post_pipeline(application, data={})

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.asyncio
async def test_pipeline_endpoint_rejects_a_blank_filename() -> None:
    application, _, service = make_pipeline_app()

    response = await post_pipeline(application, filename="   ")

    assert response.status_code == 422
    assert service.calls == []


class FakeLifecycleService:
    def __init__(self, *, item: object | None = None) -> None:
        self.item = item
        self.calls: list[UUID] = []

    async def find_item(self, *, item_id: UUID) -> object | None:
        self.calls.append(item_id)
        return self.item


def make_status_app(
    *,
    item: object | None = None,
) -> tuple[FastAPI, FakeLifecycleService]:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(api_router)
    lifecycle = FakeLifecycleService(item=item)
    application.dependency_overrides[get_local_principal_id] = lambda: _ACTOR_ID
    application.dependency_overrides[
        get_permission_authorization_service
    ] = lambda: FakePermissionAuthorizationService(allowed=True)
    application.dependency_overrides[
        get_ingestion_lifecycle_service
    ] = lambda: lifecycle
    return application, lifecycle


def make_item_state(status: IngestionStatus) -> IngestionItemState:
    return IngestionItemState(
        id=uuid4(),
        ingestion_run_id=uuid4(),
        document_artifact_id=_ARTIFACT_ID,
        status=status,
        attempt_count=1,
        claimed_at=None,
        lease_expires_at=None,
        observed_file_hash=hashlib.sha256(_CONTENT).hexdigest(),
        execution_metadata={"extraction": {"method": "openai_ocr", "block_count": 2}},
        error_code=None,
        error_message=None,
        started_at=None,
        completed_at=None,
        activated_at=None,
        deactivated_at=None,
        created_at=datetime(2026, 9, 6, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_status_endpoint_returns_the_persisted_execution_metadata() -> None:
    item = make_item_state(IngestionStatus.COMPLETED)
    application, lifecycle = make_status_app(item=item)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.get(f"/api/v1/ingestion/items/{item.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["observed_file_hash"] == hashlib.sha256(_CONTENT).hexdigest()
    assert body["execution_metadata"]["extraction"]["method"] == "openai_ocr"
    assert lifecycle.calls == [item.id]


@pytest.mark.asyncio
async def test_status_endpoint_returns_404_for_an_unknown_item() -> None:
    application, _ = make_status_app(item=None)
    unknown_id = uuid4()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.get(f"/api/v1/ingestion/items/{unknown_id}")

    assert response.status_code == 404
