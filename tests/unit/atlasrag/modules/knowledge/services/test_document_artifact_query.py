from datetime import UTC, datetime
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.documents import DocumentArtifactState, KnowledgeUnitOfWork
from atlasrag.contracts.error.document_errors import (
    DocumentArtifactNotFound,
    DocumentNotFound,
    DocumentVersionNotFound,
)
from atlasrag.contracts.types.authorization_types import (
    DocumentArtifactStatus,
    DocumentVersionStatus,
)
from atlasrag.contracts.types.document_types import DocumentState, DocumentVersionState
from atlasrag.modules.knowledge.services.document_artifact_query import (
    DocumentArtifactQueryService,
)

_NOW = datetime(2026, 8, 30, tzinfo=UTC)


class FakeDocumentRepository:
    def __init__(self, document: DocumentState | None) -> None:
        self.document = document

    async def find_active_by_id(self, *, document_id: UUID, lock: bool) -> DocumentState | None:
        if self.document is None or self.document.document_id != document_id:
            return None
        if self.document.deleted_at is not None:
            return None
        return self.document


class FakeDocumentVersionRepository:
    def __init__(self, version: DocumentVersionState | None) -> None:
        self.version = version

    async def find_by_id(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        lock: bool,
    ) -> DocumentVersionState | None:
        if self.version is None:
            return None
        if self.version.document_id != document_id or self.version.version_id != version_id:
            return None
        return self.version


class FakeDocumentArtifactRepository:
    def __init__(
        self,
        *,
        artifact: DocumentArtifactState | None = None,
        artifacts: tuple[DocumentArtifactState, ...] = (),
    ) -> None:
        self.artifact = artifact
        self.artifacts = artifacts
        self.list_calls: list[tuple[UUID, bool]] = []

    async def find_by_id(
        self,
        *,
        document_version_id: UUID,
        artifact_id: UUID,
        lock: bool,
    ) -> DocumentArtifactState | None:
        if self.artifact is None:
            return None
        if (
            self.artifact.document_version_id != document_version_id
            or self.artifact.artifact_id != artifact_id
        ):
            return None
        return self.artifact

    async def list_for_version(
        self,
        *,
        document_version_id: UUID,
        include_deleted: bool = False,
    ) -> tuple[DocumentArtifactState, ...]:
        self.list_calls.append((document_version_id, include_deleted))
        return tuple(
            artifact
            for artifact in self.artifacts
            if artifact.document_version_id == document_version_id
            and (include_deleted or artifact.status is not DocumentArtifactStatus.DELETED)
        )


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        documents: FakeDocumentRepository,
        versions: FakeDocumentVersionRepository,
        artifacts: FakeDocumentArtifactRepository,
    ) -> None:
        self.documents = documents
        self.document_versions = versions
        self.document_artifacts = artifacts

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        pass


def make_document(*, document_id: UUID, deleted_at: datetime | None = None) -> DocumentState:
    return DocumentState(
        document_id=document_id,
        created_by_principal_id=None,
        canonical_key=f"document-{document_id}",
        title="Document",
        description=None,
        document_type=None,
        department=None,
        default_language_code="en",
        metadata={},
        created_at=_NOW,
        updated_at=_NOW,
        deleted_at=deleted_at,
    )


def make_version(*, document_id: UUID, version_id: UUID) -> DocumentVersionState:
    return DocumentVersionState(
        version_id=version_id,
        document_id=document_id,
        version_label="v1",
        effective_from=None,
        effective_to=None,
        published_at=None,
        status=DocumentVersionStatus.DRAFT,
        created_by_principal_id=None,
        metadata={},
        created_at=_NOW,
        updated_at=_NOW,
    )


def make_artifact(
    *,
    artifact_id: UUID | None = None,
    document_version_id: UUID,
    status: DocumentArtifactStatus = DocumentArtifactStatus.AVAILABLE,
) -> DocumentArtifactState:
    return DocumentArtifactState(
        artifact_id=artifact_id or uuid4(),
        document_version_id=document_version_id,
        artifact_key="source",
        language_code="en",
        source_name="source.txt",
        source_uri=None,
        source_updated_at=None,
        storage_provider="s3",
        storage_key="documents/x/versions/y/artifacts/z",
        mime_type="text/plain",
        file_hash="hash",
        file_size_bytes=10,
        status=status,
        created_by_principal_id=None,
        metadata={},
        created_at=_NOW,
        updated_at=_NOW,
        retired_at=None,
        deleted_at=None,
    )


def make_service(
    *,
    document: DocumentState | None,
    version: DocumentVersionState | None,
    artifact: DocumentArtifactState | None = None,
    artifacts: tuple[DocumentArtifactState, ...] = (),
) -> tuple[DocumentArtifactQueryService, FakeUnitOfWork, FakeDocumentArtifactRepository]:
    artifact_repository = FakeDocumentArtifactRepository(artifact=artifact, artifacts=artifacts)
    uow = FakeUnitOfWork(
        documents=FakeDocumentRepository(document),
        versions=FakeDocumentVersionRepository(version),
        artifacts=artifact_repository,
    )
    service = DocumentArtifactQueryService(lambda: cast(KnowledgeUnitOfWork, uow))
    return service, uow, artifact_repository


@pytest.mark.asyncio
async def test_get_artifact_returns_details() -> None:
    document_id = uuid4()
    version_id = uuid4()
    artifact = make_artifact(document_version_id=version_id)
    service, _, _ = make_service(
        document=make_document(document_id=document_id),
        version=make_version(document_id=document_id, version_id=version_id),
        artifact=artifact,
    )

    result = await service.get_artifact(
        document_id=document_id,
        document_version_id=version_id,
        artifact_id=artifact.artifact_id,
    )

    assert result is artifact


@pytest.mark.asyncio
async def test_get_artifact_rejects_missing_document() -> None:
    document_id = uuid4()
    version_id = uuid4()
    artifact = make_artifact(document_version_id=version_id)
    service, _, _ = make_service(
        document=None,
        version=make_version(document_id=document_id, version_id=version_id),
        artifact=artifact,
    )

    with pytest.raises(DocumentNotFound):
        await service.get_artifact(
            document_id=document_id,
            document_version_id=version_id,
            artifact_id=artifact.artifact_id,
        )


@pytest.mark.asyncio
async def test_get_artifact_rejects_deleted_document() -> None:
    document_id = uuid4()
    version_id = uuid4()
    artifact = make_artifact(document_version_id=version_id)
    service, _, _ = make_service(
        document=make_document(document_id=document_id, deleted_at=_NOW),
        version=make_version(document_id=document_id, version_id=version_id),
        artifact=artifact,
    )

    with pytest.raises(DocumentNotFound):
        await service.get_artifact(
            document_id=document_id,
            document_version_id=version_id,
            artifact_id=artifact.artifact_id,
        )


@pytest.mark.asyncio
async def test_get_artifact_rejects_missing_version() -> None:
    document_id = uuid4()
    version_id = uuid4()
    artifact = make_artifact(document_version_id=version_id)
    service, _, _ = make_service(
        document=make_document(document_id=document_id),
        version=None,
        artifact=artifact,
    )

    with pytest.raises(DocumentVersionNotFound):
        await service.get_artifact(
            document_id=document_id,
            document_version_id=version_id,
            artifact_id=artifact.artifact_id,
        )


@pytest.mark.asyncio
async def test_get_artifact_rejects_version_belonging_to_another_document() -> None:
    document_id = uuid4()
    version_id = uuid4()
    other_document_id = uuid4()
    artifact = make_artifact(document_version_id=version_id)
    service, _, _ = make_service(
        document=make_document(document_id=document_id),
        version=make_version(document_id=other_document_id, version_id=version_id),
        artifact=artifact,
    )

    with pytest.raises(DocumentVersionNotFound):
        await service.get_artifact(
            document_id=document_id,
            document_version_id=version_id,
            artifact_id=artifact.artifact_id,
        )


@pytest.mark.asyncio
async def test_get_artifact_rejects_missing_artifact() -> None:
    document_id = uuid4()
    version_id = uuid4()
    service, _, _ = make_service(
        document=make_document(document_id=document_id),
        version=make_version(document_id=document_id, version_id=version_id),
        artifact=None,
    )

    with pytest.raises(DocumentArtifactNotFound):
        await service.get_artifact(
            document_id=document_id,
            document_version_id=version_id,
            artifact_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_get_artifact_rejects_artifact_belonging_to_another_version() -> None:
    document_id = uuid4()
    version_id = uuid4()
    other_version_id = uuid4()
    artifact = make_artifact(document_version_id=other_version_id)
    service, _, _ = make_service(
        document=make_document(document_id=document_id),
        version=make_version(document_id=document_id, version_id=version_id),
        artifact=artifact,
    )

    with pytest.raises(DocumentArtifactNotFound):
        await service.get_artifact(
            document_id=document_id,
            document_version_id=version_id,
            artifact_id=artifact.artifact_id,
        )


@pytest.mark.asyncio
async def test_list_artifacts_returns_all_non_deleted() -> None:
    document_id = uuid4()
    version_id = uuid4()
    available = make_artifact(
        document_version_id=version_id, status=DocumentArtifactStatus.AVAILABLE
    )
    missing = make_artifact(document_version_id=version_id, status=DocumentArtifactStatus.MISSING)
    retired = make_artifact(document_version_id=version_id, status=DocumentArtifactStatus.RETIRED)
    deleted = make_artifact(document_version_id=version_id, status=DocumentArtifactStatus.DELETED)
    service, _, repo = make_service(
        document=make_document(document_id=document_id),
        version=make_version(document_id=document_id, version_id=version_id),
        artifacts=(available, missing, retired, deleted),
    )

    result = await service.list_artifacts(document_id=document_id, document_version_id=version_id)

    result_ids = {artifact.artifact_id for artifact in result}
    assert result_ids == {available.artifact_id, missing.artifact_id, retired.artifact_id}
    assert deleted.artifact_id not in result_ids
    assert repo.list_calls == [(version_id, False)]


@pytest.mark.asyncio
async def test_list_artifacts_empty_version_returns_empty_tuple() -> None:
    document_id = uuid4()
    version_id = uuid4()
    service, _, _ = make_service(
        document=make_document(document_id=document_id),
        version=make_version(document_id=document_id, version_id=version_id),
        artifacts=(),
    )

    result = await service.list_artifacts(document_id=document_id, document_version_id=version_id)

    assert result == ()


@pytest.mark.asyncio
async def test_list_artifacts_excludes_other_versions() -> None:
    document_id = uuid4()
    version_id = uuid4()
    other_version_id = uuid4()
    own = make_artifact(document_version_id=version_id)
    other = make_artifact(document_version_id=other_version_id)
    service, _, _ = make_service(
        document=make_document(document_id=document_id),
        version=make_version(document_id=document_id, version_id=version_id),
        artifacts=(own, other),
    )

    result = await service.list_artifacts(document_id=document_id, document_version_id=version_id)

    assert result == (own,)


@pytest.mark.asyncio
async def test_list_artifacts_rejects_missing_document() -> None:
    document_id = uuid4()
    version_id = uuid4()
    service, _, _ = make_service(
        document=None,
        version=make_version(document_id=document_id, version_id=version_id),
    )

    with pytest.raises(DocumentNotFound):
        await service.list_artifacts(document_id=document_id, document_version_id=version_id)


@pytest.mark.asyncio
async def test_list_artifacts_rejects_version_belonging_to_another_document() -> None:
    document_id = uuid4()
    version_id = uuid4()
    other_document_id = uuid4()
    service, _, _ = make_service(
        document=make_document(document_id=document_id),
        version=make_version(document_id=other_document_id, version_id=version_id),
    )

    with pytest.raises(DocumentVersionNotFound):
        await service.list_artifacts(document_id=document_id, document_version_id=version_id)


@pytest.mark.asyncio
async def test_cross_document_artifact_lookup_is_not_found() -> None:
    document_1 = uuid4()
    version_1 = uuid4()
    version_2 = uuid4()
    artifact = make_artifact(document_version_id=version_2)
    service, _, _ = make_service(
        document=make_document(document_id=document_1),
        version=make_version(document_id=document_1, version_id=version_1),
        artifact=artifact,
    )

    with pytest.raises(DocumentArtifactNotFound):
        await service.get_artifact(
            document_id=document_1,
            document_version_id=version_1,
            artifact_id=artifact.artifact_id,
        )
