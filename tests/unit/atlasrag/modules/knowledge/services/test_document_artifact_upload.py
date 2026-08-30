import hashlib
from datetime import UTC, datetime
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.documents import (
    CreateDocumentArtifact,
    KnowledgeUnitOfWork,
    UploadDocumentArtifact,
)
from atlasrag.contracts.error.document_errors import (
    DocumentArtifactConflict,
    DocumentArtifactContentTypeInvalid,
    DocumentArtifactEmpty,
    DocumentArtifactKeyInvalid,
    DocumentArtifactLanguageCodeInvalid,
    DocumentArtifactStorageLocationConflict,
    DocumentArtifactTooLarge,
    DocumentArtifactVersionNotDraft,
    DocumentDeleted,
    DocumentNotFound,
    DocumentVersionNotFound,
)
from atlasrag.contracts.types.authorization_types import DocumentVersionStatus
from atlasrag.contracts.types.document_types import DocumentState, DocumentVersionState
from atlasrag.modules.knowledge.services.document_artifact_upload import (
    DocumentArtifactUploadService,
)

_NOW = datetime(2026, 8, 30, tzinfo=UTC)
_MAX_FILE_SIZE_BYTES = 16


def expected_storage_key(
    *,
    document_id: UUID,
    version_id: UUID,
    artifact_id: UUID,
) -> str:
    return f"documents/{document_id}/versions/{version_id}/artifacts/{artifact_id}"


class FakeDocumentRepository:
    def __init__(self, document: DocumentState | None) -> None:
        self.document = document
        self.find_calls: list[tuple[UUID, bool]] = []

    async def find_by_id(self, *, document_id: UUID, lock: bool) -> DocumentState | None:
        self.find_calls.append((document_id, lock))
        if self.document is None or self.document.document_id != document_id:
            return None
        return self.document


class FakeDocumentVersionRepository:
    def __init__(self, version: DocumentVersionState | None) -> None:
        self.version = version
        self.find_calls: list[tuple[UUID, UUID, bool]] = []

    async def find_by_id(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        lock: bool,
    ) -> DocumentVersionState | None:
        self.find_calls.append((document_id, version_id, lock))
        if self.version is None:
            return None
        if self.version.document_id != document_id or self.version.version_id != version_id:
            return None
        return self.version


class FakeDocumentArtifactRepository:
    def __init__(
        self,
        *,
        artifact_key_exists: bool = False,
        storage_key_exists: bool = False,
        add_error: BaseException | None = None,
    ) -> None:
        self._artifact_key_exists = artifact_key_exists
        self._storage_key_exists = storage_key_exists
        self._add_error = add_error
        self.artifact_key_checks: list[tuple[UUID, str]] = []
        self.storage_key_checks: list[tuple[str, str]] = []
        self.add_calls: list[CreateDocumentArtifact] = []

    async def artifact_key_exists(
        self,
        *,
        document_version_id: UUID,
        artifact_key: str,
    ) -> bool:
        self.artifact_key_checks.append((document_version_id, artifact_key))
        return self._artifact_key_exists

    async def storage_key_exists(
        self,
        *,
        storage_provider: str,
        storage_key: str,
    ) -> bool:
        self.storage_key_checks.append((storage_provider, storage_key))
        return self._storage_key_exists

    async def add(self, *, artifact: CreateDocumentArtifact) -> None:
        self.add_calls.append(artifact)
        if self._add_error is not None:
            raise self._add_error


class FakeObjectStorage:
    def __init__(
        self,
        *,
        put_error: BaseException | None = None,
        delete_error: BaseException | None = None,
    ) -> None:
        self._put_error = put_error
        self._delete_error = delete_error
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_calls: list[tuple[str, bytes, str]] = []
        self.delete_calls: list[str] = []

    async def put(self, *, key: str, content: bytes, content_type: str) -> None:
        self.put_calls.append((key, content, content_type))
        if self._put_error is not None:
            raise self._put_error
        self.objects[key] = (content, content_type)

    async def get(self, *, key: str) -> bytes:
        return self.objects[key][0]

    async def delete(self, *, key: str) -> None:
        self.delete_calls.append(key)
        if self._delete_error is not None:
            raise self._delete_error
        self.objects.pop(key, None)

    async def exists(self, *, key: str) -> bool:
        return key in self.objects


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        documents: FakeDocumentRepository,
        versions: FakeDocumentVersionRepository,
        artifacts: FakeDocumentArtifactRepository,
        commit_error: BaseException | None = None,
    ) -> None:
        self.documents = documents
        self.document_versions = versions
        self.document_artifacts = artifacts
        self._commit_error = commit_error
        self.committed = False
        self.rolled_back = False
        self.exit_exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exit_exception_type = exc_type
        if exc_type is not None or not self.committed:
            self.rolled_back = True

    async def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error
        self.committed = True


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


def make_version(
    *,
    document_id: UUID,
    version_id: UUID,
    status: DocumentVersionStatus = DocumentVersionStatus.DRAFT,
) -> DocumentVersionState:
    return DocumentVersionState(
        version_id=version_id,
        document_id=document_id,
        version_label="v1",
        effective_from=None,
        effective_to=None,
        published_at=None,
        status=status,
        created_by_principal_id=None,
        metadata={},
        created_at=_NOW,
        updated_at=_NOW,
    )


def make_command(
    *,
    document_id: UUID | None = None,
    version_id: UUID | None = None,
    artifact_key: str = "source",
    language_code: str = "en",
    content_type: str = "text/plain",
    content: bytes = b"artifact bytes",
) -> UploadDocumentArtifact:
    return UploadDocumentArtifact(
        document_id=document_id or uuid4(),
        document_version_id=version_id or uuid4(),
        artifact_key=artifact_key,
        language_code=language_code,
        source_name="source.txt",
        source_uri="https://example.test/source.txt",
        source_updated_at=_NOW,
        content_type=content_type,
        content=content,
    )


def make_service(
    *,
    command: UploadDocumentArtifact,
    artifact_id: UUID | None = None,
    document: DocumentState | None = None,
    version: DocumentVersionState | None = None,
    artifacts: FakeDocumentArtifactRepository | None = None,
    storage: FakeObjectStorage | None = None,
    commit_error: BaseException | None = None,
) -> tuple[
    DocumentArtifactUploadService,
    FakeUnitOfWork,
    FakeDocumentArtifactRepository,
    FakeObjectStorage,
    UUID,
]:
    generated_artifact_id = artifact_id or uuid4()
    artifact_repository = artifacts or FakeDocumentArtifactRepository()
    object_storage = storage or FakeObjectStorage()
    uow = FakeUnitOfWork(
        documents=FakeDocumentRepository(
            document
            if document is not None
            else make_document(document_id=command.document_id)
        ),
        versions=FakeDocumentVersionRepository(
            version
            if version is not None
            else make_version(
                document_id=command.document_id,
                version_id=command.document_version_id,
            )
        ),
        artifacts=artifact_repository,
        commit_error=commit_error,
    )
    service = DocumentArtifactUploadService(
        lambda: cast(KnowledgeUnitOfWork, uow),
        object_storage=object_storage,
        max_file_size_bytes=_MAX_FILE_SIZE_BYTES,
        accepted_language_codes={"ar", "en"},
        allowed_content_types={
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/html",
            "text/markdown",
            "text/plain",
        },
        artifact_key_max_length=255,
        language_code_max_length=20,
        storage_provider="s3",
        artifact_id_factory=lambda: generated_artifact_id,
        clock=lambda: _NOW,
    )
    return service, uow, artifact_repository, object_storage, generated_artifact_id


@pytest.mark.asyncio
async def test_upload_stores_bytes_and_creates_artifact_metadata() -> None:
    command = make_command(content=b"hello atlas")
    actor_id = uuid4()
    service, uow, artifacts, storage, artifact_id = make_service(command=command)
    storage_key = expected_storage_key(
        document_id=command.document_id,
        version_id=command.document_version_id,
        artifact_id=artifact_id,
    )
    expected_hash = hashlib.sha256(command.content).hexdigest()

    result = await service.upload(command, actor_principal_id=actor_id)

    assert storage.put_calls == [(storage_key, command.content, command.content_type)]
    assert storage.objects[storage_key] == (command.content, command.content_type)
    assert len(artifacts.add_calls) == 1
    created = artifacts.add_calls[0]
    assert created.artifact_id == artifact_id
    assert created.storage_provider == "s3"
    assert created.storage_key == storage_key
    assert created.file_hash == expected_hash
    assert created.file_size_bytes == len(command.content)
    assert created.created_by_principal_id == actor_id
    assert created.created_at == _NOW
    assert created.metadata == {}
    assert result.artifact_id == artifact_id
    assert result.file_hash == expected_hash
    assert result.file_size_bytes == len(command.content)
    assert uow.committed is True
    assert uow.rolled_back is False


@pytest.mark.asyncio
async def test_upload_rejects_missing_document() -> None:
    command = make_command()
    service, uow, artifacts, storage, _ = make_service(command=command)
    uow.documents.document = None

    with pytest.raises(DocumentNotFound):
        await service.upload(command, actor_principal_id=uuid4())

    assert artifacts.add_calls == []
    assert storage.put_calls == []
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_upload_rejects_deleted_document() -> None:
    command = make_command()
    deleted_document = make_document(document_id=command.document_id, deleted_at=_NOW)
    service, uow, artifacts, storage, _ = make_service(
        command=command,
        document=deleted_document,
    )

    with pytest.raises(DocumentDeleted):
        await service.upload(command, actor_principal_id=uuid4())

    assert artifacts.add_calls == []
    assert storage.put_calls == []
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_upload_rejects_missing_version() -> None:
    command = make_command()
    service, uow, artifacts, storage, _ = make_service(command=command)
    uow.document_versions.version = None

    with pytest.raises(DocumentVersionNotFound):
        await service.upload(command, actor_principal_id=uuid4())

    assert artifacts.add_calls == []
    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_upload_rejects_version_belonging_to_another_document() -> None:
    command = make_command()
    other_document_version = make_version(
        document_id=uuid4(),
        version_id=command.document_version_id,
    )
    service, _, artifacts, storage, _ = make_service(
        command=command,
        version=other_document_version,
    )

    with pytest.raises(DocumentVersionNotFound):
        await service.upload(command, actor_principal_id=uuid4())

    assert artifacts.add_calls == []
    assert storage.put_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        DocumentVersionStatus.PUBLISHED,
        DocumentVersionStatus.WITHDRAWN,
        DocumentVersionStatus.ARCHIVED,
    ],
)
async def test_upload_rejects_non_draft_version(status: DocumentVersionStatus) -> None:
    command = make_command()
    service, _, artifacts, storage, _ = make_service(
        command=command,
        version=make_version(
            document_id=command.document_id,
            version_id=command.document_version_id,
            status=status,
        ),
    )

    with pytest.raises(DocumentArtifactVersionNotDraft):
        await service.upload(command, actor_principal_id=uuid4())

    assert artifacts.add_calls == []
    assert storage.put_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "expected_error"),
    [
        (make_command(artifact_key="   "), DocumentArtifactKeyInvalid),
        (make_command(artifact_key="a" * 256), DocumentArtifactKeyInvalid),
        (make_command(language_code="fr"), DocumentArtifactLanguageCodeInvalid),
        (make_command(content_type="application/json"), DocumentArtifactContentTypeInvalid),
        (make_command(content=b""), DocumentArtifactEmpty),
        (make_command(content=b"a" * 17), DocumentArtifactTooLarge),
    ],
)
async def test_upload_rejects_invalid_file_before_storage(
    command: UploadDocumentArtifact,
    expected_error: type[BaseException],
) -> None:
    service, _, artifacts, storage, _ = make_service(command=command)

    with pytest.raises(expected_error):
        await service.upload(command, actor_principal_id=uuid4())

    assert artifacts.add_calls == []
    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_upload_rejects_existing_artifact_key_before_storage() -> None:
    command = make_command()
    artifact_repository = FakeDocumentArtifactRepository(artifact_key_exists=True)
    service, _, artifacts, storage, _ = make_service(
        command=command,
        artifacts=artifact_repository,
    )

    with pytest.raises(DocumentArtifactConflict):
        await service.upload(command, actor_principal_id=uuid4())

    assert artifacts.add_calls == []
    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_upload_rejects_existing_generated_storage_key() -> None:
    command = make_command()
    artifact_repository = FakeDocumentArtifactRepository(storage_key_exists=True)
    service, _, artifacts, storage, _ = make_service(
        command=command,
        artifacts=artifact_repository,
    )

    with pytest.raises(DocumentArtifactStorageLocationConflict):
        await service.upload(command, actor_principal_id=uuid4())

    assert artifacts.add_calls == []
    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_storage_failure_rolls_back_without_creating_or_deleting_artifact() -> None:
    command = make_command()
    storage_error = RuntimeError("storage unavailable")
    object_storage = FakeObjectStorage(put_error=storage_error)
    service, uow, artifacts, storage, _ = make_service(
        command=command,
        storage=object_storage,
    )

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await service.upload(command, actor_principal_id=uuid4())

    assert artifacts.add_calls == []
    assert storage.delete_calls == []
    assert uow.committed is False
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_and_compensates_uploaded_object() -> None:
    command = make_command()
    commit_error = RuntimeError("commit failed")
    service, uow, artifacts, storage, artifact_id = make_service(
        command=command,
        commit_error=commit_error,
    )
    storage_key = expected_storage_key(
        document_id=command.document_id,
        version_id=command.document_version_id,
        artifact_id=artifact_id,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.upload(command, actor_principal_id=uuid4())

    assert len(artifacts.add_calls) == 1
    assert storage.delete_calls == [storage_key]
    assert storage.objects == {}
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_duplicate_race_conflict_compensates_uploaded_object() -> None:
    command = make_command()
    conflict = DocumentArtifactConflict(
        document_version_id=command.document_version_id,
        artifact_key=command.artifact_key,
    )
    artifact_repository = FakeDocumentArtifactRepository(add_error=conflict)
    service, uow, _, storage, artifact_id = make_service(
        command=command,
        artifacts=artifact_repository,
    )
    storage_key = expected_storage_key(
        document_id=command.document_id,
        version_id=command.document_version_id,
        artifact_id=artifact_id,
    )

    with pytest.raises(DocumentArtifactConflict) as error:
        await service.upload(command, actor_principal_id=uuid4())

    assert error.value is conflict
    assert storage.delete_calls == [storage_key]
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_compensation_failure_preserves_database_error() -> None:
    command = make_command()
    object_storage = FakeObjectStorage(delete_error=RuntimeError("delete failed"))
    service, uow, _, storage, _ = make_service(
        command=command,
        storage=object_storage,
        commit_error=RuntimeError("commit failed"),
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.upload(command, actor_principal_id=uuid4())

    assert len(storage.delete_calls) == 1
    assert len(storage.objects) == 1
    assert uow.rolled_back is True
