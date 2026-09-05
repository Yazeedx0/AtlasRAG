import hashlib
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from atlasrag.contracts.error.object_storage_errors import (
    ObjectNotFound,
    ObjectStorageUnavailable,
)
from atlasrag.contracts.types.ingestion import ClaimedIngestionItem, LoadedArtifact
from atlasrag.modules.ingestion.services.artifact_loader import (
    ArtifactIntegrityMismatch,
    ArtifactLoader,
    ArtifactUnavailableForIngestion,
)
from atlasrag.modules.ingestion.workers.default_processor import DefaultIngestionProcessor
from atlasrag.modules.ingestion.workers.errors import (
    PermanentIngestionError,
    TransientIngestionError,
)

_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


class FakeArtifactLoader:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.artifact_ids: list[UUID] = []

    async def load(self, *, artifact_id: UUID) -> LoadedArtifact:
        self.artifact_ids.append(artifact_id)
        if self._error is not None:
            raise self._error
        content = b"verified"
        digest = hashlib.sha256(content).hexdigest()
        return LoadedArtifact(
            artifact_id=uuid4(),
            content=content,
            mime_type="text/plain",
            expected_file_hash=digest,
            observed_file_hash=digest,
            file_size_bytes=len(content),
        )


def make_claim() -> ClaimedIngestionItem:
    return ClaimedIngestionItem(
        ingestion_item_id=uuid4(),
        document_artifact_id=uuid4(),
        attempt_number=1,
        claimed_at=_NOW,
        lease_expires_at=_NOW + timedelta(minutes=2),
    )


def make_processor(loader: FakeArtifactLoader) -> DefaultIngestionProcessor:
    return DefaultIngestionProcessor(artifact_loader=cast(ArtifactLoader, loader))


@pytest.mark.asyncio
async def test_processor_loads_the_claimed_artifact() -> None:
    claim = make_claim()
    loader = FakeArtifactLoader()

    await make_processor(loader).process(claim=claim)

    assert loader.artifact_ids == [claim.document_artifact_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "error_code"),
    [
        (
            ArtifactUnavailableForIngestion(artifact_id=uuid4(), status=None),
            "artifact_unavailable_for_ingestion",
        ),
        (
            ArtifactIntegrityMismatch(
                artifact_id=uuid4(),
                expected_file_hash="a" * 64,
                observed_file_hash="b" * 64,
                expected_file_size_bytes=1,
                observed_file_size_bytes=1,
            ),
            "artifact_integrity_mismatch",
        ),
        (ObjectNotFound(key="documents/missing"), "artifact_object_missing"),
    ],
)
async def test_permanent_artifact_failures_are_classified_as_permanent(
    error: Exception,
    error_code: str,
) -> None:
    processor = make_processor(FakeArtifactLoader(error=error))

    with pytest.raises(PermanentIngestionError) as raised:
        await processor.process(claim=make_claim())

    assert raised.value.error_code == error_code


@pytest.mark.asyncio
async def test_temporary_storage_failure_is_classified_as_transient() -> None:
    processor = make_processor(
        FakeArtifactLoader(
            error=ObjectStorageUnavailable(operation="get", key="documents/source"),
        )
    )

    with pytest.raises(TransientIngestionError):
        await processor.process(claim=make_claim())
