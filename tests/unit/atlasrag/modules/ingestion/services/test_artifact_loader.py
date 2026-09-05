import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.error.object_storage_errors import ObjectNotFound
from atlasrag.contracts.types.authorization import DocumentArtifactStatus
from atlasrag.contracts.types.document import DocumentArtifactState
from atlasrag.modules.ingestion.services.artifact_loader import (
    ArtifactIntegrityMismatch,
    ArtifactLoader,
    ArtifactUnavailableForIngestion,
)

_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


class FakeArtifactRepository:
    def __init__(self, artifact: DocumentArtifactState | None) -> None:
        self.artifact = artifact
        self.calls: list[UUID] = []

    async def find_for_ingestion(self, *, artifact_id: UUID) -> DocumentArtifactState | None:
        self.calls.append(artifact_id)
        return self.artifact


class FakeObjectStorage:
    def __init__(self, *, content: bytes = b"", error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.keys: list[str] = []

    async def get(self, *, key: str) -> bytes:
        self.keys.append(key)
        if self._error is not None:
            raise self._error
        return self._content


def make_artifact(
    *,
    artifact_id: UUID | None = None,
    content: bytes = b"verified artifact",
    file_hash: str | None = None,
    file_size_bytes: int | None = None,
    status: DocumentArtifactStatus = DocumentArtifactStatus.AVAILABLE,
) -> DocumentArtifactState:
    return DocumentArtifactState(
        artifact_id=artifact_id or uuid4(),
        document_version_id=uuid4(),
        artifact_key="source",
        language_code="en",
        source_name="source.txt",
        source_uri=None,
        source_updated_at=None,
        storage_provider="s3",
        storage_key="documents/source.txt",
        mime_type="text/plain",
        file_hash=file_hash or hashlib.sha256(content).hexdigest(),
        file_size_bytes=file_size_bytes if file_size_bytes is not None else len(content),
        status=status,
        created_by_principal_id=None,
        metadata={},
        created_at=_NOW,
        updated_at=_NOW,
        retired_at=None,
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_available_artifact_loads_verified_bytes_and_metadata() -> None:
    content = b"verified artifact"
    artifact = make_artifact(content=content)
    repository = FakeArtifactRepository(artifact)
    storage = FakeObjectStorage(content=content)
    loader = ArtifactLoader(artifact_repository=repository, object_storage=storage)

    loaded = await loader.load(artifact_id=artifact.artifact_id)

    assert repository.calls == [artifact.artifact_id]
    assert storage.keys == [artifact.storage_key]
    assert loaded.artifact_id == artifact.artifact_id
    assert loaded.content == content
    assert loaded.mime_type == artifact.mime_type
    assert loaded.expected_file_hash == artifact.file_hash
    assert loaded.observed_file_hash == hashlib.sha256(content).hexdigest()
    assert loaded.file_size_bytes == len(content)


@pytest.mark.asyncio
async def test_missing_artifact_is_rejected_before_storage_read() -> None:
    artifact_id = uuid4()
    repository = FakeArtifactRepository(None)
    storage = FakeObjectStorage(content=b"unexpected")
    loader = ArtifactLoader(artifact_repository=repository, object_storage=storage)

    with pytest.raises(ArtifactUnavailableForIngestion) as error:
        await loader.load(artifact_id=artifact_id)

    assert error.value.status is None
    assert storage.keys == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        DocumentArtifactStatus.MISSING,
        DocumentArtifactStatus.RETIRED,
        DocumentArtifactStatus.DELETED,
    ],
)
async def test_non_available_artifact_is_rejected_before_storage_read(
    status: DocumentArtifactStatus,
) -> None:
    artifact = make_artifact(status=status)
    storage = FakeObjectStorage(content=b"unexpected")
    loader = ArtifactLoader(
        artifact_repository=FakeArtifactRepository(artifact),
        object_storage=storage,
    )

    with pytest.raises(ArtifactUnavailableForIngestion) as error:
        await loader.load(artifact_id=artifact.artifact_id)

    assert error.value.status is status
    assert storage.keys == []


@pytest.mark.asyncio
async def test_storage_object_missing_is_propagated() -> None:
    artifact = make_artifact()
    storage = FakeObjectStorage(error=ObjectNotFound(key=artifact.storage_key))
    loader = ArtifactLoader(
        artifact_repository=FakeArtifactRepository(artifact),
        object_storage=storage,
    )

    with pytest.raises(ObjectNotFound):
        await loader.load(artifact_id=artifact.artifact_id)


@pytest.mark.asyncio
async def test_hash_mismatch_returns_integrity_diagnostics() -> None:
    expected_content = b"expected artifact"
    observed_content = b"observed artifact"
    artifact = make_artifact(content=expected_content)
    loader = ArtifactLoader(
        artifact_repository=FakeArtifactRepository(artifact),
        object_storage=FakeObjectStorage(content=observed_content),
    )

    with pytest.raises(ArtifactIntegrityMismatch) as error:
        await loader.load(artifact_id=artifact.artifact_id)

    assert error.value.expected_file_hash == hashlib.sha256(expected_content).hexdigest()
    assert error.value.observed_file_hash == hashlib.sha256(observed_content).hexdigest()
    assert error.value.expected_file_size_bytes == len(expected_content)
    assert error.value.observed_file_size_bytes == len(observed_content)


@pytest.mark.asyncio
async def test_size_mismatch_is_detected_even_when_hash_matches() -> None:
    content = b"verified artifact"
    artifact = make_artifact(content=content, file_size_bytes=len(content) + 1)
    loader = ArtifactLoader(
        artifact_repository=FakeArtifactRepository(artifact),
        object_storage=FakeObjectStorage(content=content),
    )

    with pytest.raises(ArtifactIntegrityMismatch) as error:
        await loader.load(artifact_id=artifact.artifact_id)

    assert error.value.expected_file_hash == error.value.observed_file_hash
    assert error.value.expected_file_size_bytes == len(content) + 1
    assert error.value.observed_file_size_bytes == len(content)
