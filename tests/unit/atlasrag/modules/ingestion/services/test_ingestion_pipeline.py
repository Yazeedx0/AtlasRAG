import hashlib
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.documents import (
    UploadDocumentArtifact,
    UploadedDocumentArtifact,
)
from atlasrag.contracts.types.document import DocumentState, DocumentVersionState
from atlasrag.contracts.types.ingestion import IngestionStatus
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.services.ingestion_pipeline import (
    IngestDocument,
    IngestionPipelineService,
)
from atlasrag.modules.knowledge.services.document_artifact_upload import (
    DocumentArtifactUploadService,
)
from atlasrag.modules.knowledge.services.document_management import (
    DocumentManagementService,
)
from atlasrag.modules.knowledge.services.document_version_management import (
    DocumentVersionManagementService,
)

_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
_ACTOR_ID = uuid4()
_CONTENT = b"AtlasRAG pipeline document"


class FakeDocumentService:
    def __init__(self) -> None:
        self.document_id = uuid4()
        self.calls: list[dict[str, object]] = []

    async def create_document(self, **kwargs: object) -> DocumentState:
        self.calls.append(kwargs)
        return DocumentState(
            document_id=self.document_id,
            created_by_principal_id=_ACTOR_ID,
            canonical_key=cast(str, kwargs["canonical_key"]),
            title=cast(str, kwargs["title"]),
            description=None,
            document_type=None,
            department=None,
            default_language_code=cast(str | None, kwargs["default_language_code"]),
            metadata={},
            created_at=_NOW,
            updated_at=_NOW,
            deleted_at=None,
        )


class FakeVersionService:
    def __init__(self) -> None:
        self.version_id = uuid4()
        self.calls: list[dict[str, object]] = []

    async def create_version(self, **kwargs: object) -> DocumentVersionState:
        self.calls.append(kwargs)
        return DocumentVersionState(
            version_id=self.version_id,
            document_id=cast(UUID, kwargs["document_id"]),
            version_label=cast(str, kwargs["version_label"]),
            effective_from=None,
            effective_to=None,
            published_at=None,
            status=None,
            created_by_principal_id=_ACTOR_ID,
            metadata={},
            created_at=_NOW,
            updated_at=_NOW,
        )


class FakeUploadService:
    def __init__(self) -> None:
        self.artifact_id = uuid4()
        self.commands: list[UploadDocumentArtifact] = []

    async def upload(
        self,
        command: UploadDocumentArtifact,
        *,
        actor_principal_id: UUID,
    ) -> UploadedDocumentArtifact:
        self.commands.append(command)
        return UploadedDocumentArtifact(
            artifact_id=self.artifact_id,
            document_version_id=command.document_version_id,
            artifact_key=command.artifact_key,
            language_code=command.language_code,
            mime_type=command.content_type,
            file_hash=hashlib.sha256(command.content).hexdigest(),
            file_size_bytes=len(command.content),
        )


class FakeLifecycleService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.run_id = uuid4()
        self.item_id = uuid4()
        self.runs: list[dict[str, object]] = []
        self.items: list[dict[str, object]] = []

    async def create_run(self, **kwargs: object) -> UUID:
        self.runs.append(kwargs)
        return self.run_id

    async def add_item(self, **kwargs: object) -> UUID:
        self.items.append(kwargs)
        if self._error is not None:
            raise self._error
        return self.item_id


def make_service(
    *,
    documents: FakeDocumentService | None = None,
    versions: FakeVersionService | None = None,
    uploads: FakeUploadService | None = None,
    lifecycle: FakeLifecycleService | None = None,
) -> tuple[
    IngestionPipelineService,
    FakeDocumentService,
    FakeVersionService,
    FakeUploadService,
    FakeLifecycleService,
]:
    document_service = documents or FakeDocumentService()
    version_service = versions or FakeVersionService()
    upload_service = uploads or FakeUploadService()
    lifecycle_service = lifecycle or FakeLifecycleService()
    service = IngestionPipelineService(
        document_service=cast(DocumentManagementService, document_service),
        version_service=cast(DocumentVersionManagementService, version_service),
        upload_service=cast(DocumentArtifactUploadService, upload_service),
        lifecycle=cast(IngestionLifecycleService, lifecycle_service),
    )
    return service, document_service, version_service, upload_service, lifecycle_service


def make_command(**overrides: object) -> IngestDocument:
    defaults: dict[str, object] = {
        "title": "Employee Handbook",
        "source_name": "handbook.pdf",
        "content_type": "application/pdf",
        "content": _CONTENT,
        "language_code": "ar",
    }
    defaults.update(overrides)
    return IngestDocument(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_pipeline_creates_document_version_and_artifact_then_extracts() -> None:
    service, documents, versions, uploads, lifecycle = make_service()

    queued = await service.ingest(make_command(), actor_principal_id=_ACTOR_ID)

    assert queued.document_id == documents.document_id
    assert queued.document_version_id == versions.version_id
    assert queued.artifact_id == uploads.artifact_id
    assert queued.ingestion_run_id == lifecycle.run_id
    assert queued.ingestion_item_id == lifecycle.item_id
    assert queued.status is IngestionStatus.PENDING
    assert lifecycle.items[0]["document_artifact_id"] == uploads.artifact_id
    assert lifecycle.items[0]["ingestion_run_id"] == lifecycle.run_id


@pytest.mark.asyncio
async def test_uploaded_artifact_is_linked_to_the_created_document_and_version() -> None:
    service, documents, versions, uploads, _ = make_service()

    await service.ingest(make_command(), actor_principal_id=_ACTOR_ID)

    command = uploads.commands[0]
    assert command.document_id == documents.document_id
    assert command.document_version_id == versions.version_id
    assert command.content == _CONTENT
    assert command.content_type == "application/pdf"
    assert command.source_name == "handbook.pdf"


@pytest.mark.asyncio
async def test_a_canonical_key_is_generated_when_the_caller_omits_one() -> None:
    service, documents, _, _, _ = make_service()

    first = await service.ingest(make_command(), actor_principal_id=_ACTOR_ID)
    second = await service.ingest(make_command(), actor_principal_id=_ACTOR_ID)

    assert first.canonical_key.startswith("ingestion-")
    assert first.canonical_key != second.canonical_key
    assert documents.calls[0]["canonical_key"] == first.canonical_key


@pytest.mark.asyncio
async def test_an_explicit_canonical_key_is_used_verbatim() -> None:
    service, documents, _, _, _ = make_service()

    ingested = await service.ingest(
        make_command(canonical_key="hr/handbook/2026"),
        actor_principal_id=_ACTOR_ID,
    )

    assert ingested.canonical_key == "hr/handbook/2026"
    assert documents.calls[0]["canonical_key"] == "hr/handbook/2026"


@pytest.mark.asyncio
async def test_version_and_artifact_labels_default_and_can_be_overridden() -> None:
    service, _, versions, uploads, _ = make_service()

    await service.ingest(make_command(), actor_principal_id=_ACTOR_ID)
    assert versions.calls[0]["version_label"] == "v1"
    assert uploads.commands[0].artifact_key == "source"

    await service.ingest(
        make_command(version_label="v2", artifact_key="scanned"),
        actor_principal_id=_ACTOR_ID,
    )
    assert versions.calls[1]["version_label"] == "v2"
    assert uploads.commands[1].artifact_key == "scanned"


@pytest.mark.asyncio
async def test_the_actor_is_recorded_on_every_created_row() -> None:
    service, documents, versions, _, _ = make_service()

    await service.ingest(make_command(), actor_principal_id=_ACTOR_ID)

    assert documents.calls[0]["actor_principal_id"] == _ACTOR_ID
    assert versions.calls[0]["actor_principal_id"] == _ACTOR_ID


@pytest.mark.asyncio
async def test_enqueue_failures_propagate_to_the_caller() -> None:
    service, _, _, _, _ = make_service(
        lifecycle=FakeLifecycleService(error=RuntimeError("outbox exploded"))
    )

    with pytest.raises(RuntimeError):
        await service.ingest(make_command(), actor_principal_id=_ACTOR_ID)
