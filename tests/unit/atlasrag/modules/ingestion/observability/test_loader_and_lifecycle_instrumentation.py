import hashlib
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID, uuid4

import pytest
from tests.unit.conftest import ObservabilityHarness

from atlasrag.contracts.ingestion import IngestionUnitOfWork
from atlasrag.contracts.types.authorization import DocumentArtifactStatus
from atlasrag.contracts.types.document import DocumentArtifactState
from atlasrag.contracts.types.jobs import JobType
from atlasrag.contracts.types.observability import (
    JobStage,
    LabelKey,
    MetricName,
    SpanName,
)
from atlasrag.modules.ingestion.services.artifact_loader import (
    ArtifactIntegrityMismatch,
    ArtifactLoader,
    ArtifactUnavailableForIngestion,
)
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.platform.observability import (
    current_language,
    failed_stage,
    ingestion_job_context,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
_CONTENT = b"verified artifact bytes"
_DIGEST = hashlib.sha256(_CONTENT).hexdigest()


def make_artifact_state(
    *,
    language_code: str = "ar",
    status: DocumentArtifactStatus = DocumentArtifactStatus.AVAILABLE,
    file_hash: str = _DIGEST,
    file_size_bytes: int = len(_CONTENT),
) -> DocumentArtifactState:
    return DocumentArtifactState(
        artifact_id=uuid4(),
        document_version_id=uuid4(),
        artifact_key="source",
        language_code=language_code,
        source_name="handbook.pdf",
        source_uri=None,
        source_updated_at=None,
        storage_provider="s3",
        storage_key="artifacts/handbook.pdf",
        mime_type="application/pdf",
        file_hash=file_hash,
        file_size_bytes=file_size_bytes,
        status=status,
        created_by_principal_id=None,
        metadata={},
        created_at=_NOW,
        updated_at=_NOW,
        retired_at=None,
        deleted_at=None,
    )


class FakeArtifactRepository:
    def __init__(self, artifact: DocumentArtifactState | None) -> None:
        self._artifact = artifact

    async def find_for_ingestion(self, *, artifact_id: UUID) -> DocumentArtifactState | None:
        return self._artifact


class FakeObjectStorage:
    def __init__(self, content: bytes = _CONTENT) -> None:
        self._content = content

    async def get(self, *, key: str) -> bytes:
        return self._content


def make_loader(
    *,
    artifact: DocumentArtifactState | None,
    content: bytes = _CONTENT,
) -> ArtifactLoader:
    return ArtifactLoader(
        artifact_repository=FakeArtifactRepository(artifact),  # type: ignore[arg-type]
        object_storage=FakeObjectStorage(content),  # type: ignore[arg-type]
    )


async def test_artifact_load_emits_load_and_integrity_spans(
    observability: ObservabilityHarness,
) -> None:
    loader = make_loader(artifact=make_artifact_state())

    with ingestion_job_context(job_type=JobType.PROCESS_INGESTION_ITEM.value):
        await loader.load(artifact_id=uuid4())

    names = observability.span_names()
    assert SpanName.ARTIFACT_LOAD.value in names
    assert SpanName.ARTIFACT_INTEGRITY.value in names


async def test_artifact_load_binds_the_language_for_later_stages(
    observability: ObservabilityHarness,
) -> None:
    _ = observability
    loader = make_loader(artifact=make_artifact_state(language_code="ar"))

    with ingestion_job_context(job_type=JobType.PROCESS_INGESTION_ITEM.value):
        await loader.load(artifact_id=uuid4())
        assert current_language().value == "ar"


async def test_artifact_load_duration_is_recorded_with_its_language(
    observability: ObservabilityHarness,
) -> None:
    loader = make_loader(artifact=make_artifact_state(language_code="en"))

    with ingestion_job_context(job_type=JobType.PROCESS_INGESTION_ITEM.value):
        await loader.load(artifact_id=uuid4())

    assert (
        observability.metrics.histogram_count(
            MetricName.ARTIFACT_LOAD_DURATION_SECONDS,
            labels={LabelKey.LANGUAGE: "en", LabelKey.STATUS: "success"},
        )
        == 1
    )


async def test_an_integrity_mismatch_fails_the_integrity_stage(
    observability: ObservabilityHarness,
) -> None:
    loader = make_loader(
        artifact=make_artifact_state(file_hash="0" * 64),
        content=_CONTENT,
    )

    with ingestion_job_context(job_type=JobType.PROCESS_INGESTION_ITEM.value):
        with pytest.raises(ArtifactIntegrityMismatch):
            await loader.load(artifact_id=uuid4())

        assert failed_stage() is JobStage.ARTIFACT_INTEGRITY

    assert (
        observability.metrics.histogram_count(
            MetricName.ARTIFACT_LOAD_DURATION_SECONDS,
            labels={LabelKey.LANGUAGE: "ar", LabelKey.STATUS: "failure"},
        )
        == 1
    )


async def test_a_missing_artifact_fails_the_load_stage(
    observability: ObservabilityHarness,
) -> None:
    _ = observability
    loader = make_loader(artifact=None)

    with ingestion_job_context(job_type=JobType.PROCESS_INGESTION_ITEM.value):
        with pytest.raises(ArtifactUnavailableForIngestion):
            await loader.load(artifact_id=uuid4())

        assert failed_stage() is JobStage.ARTIFACT_LOAD


async def test_artifact_spans_never_carry_document_bytes(
    observability: ObservabilityHarness,
) -> None:
    loader = make_loader(artifact=make_artifact_state())

    with ingestion_job_context(job_type=JobType.PROCESS_INGESTION_ITEM.value):
        await loader.load(artifact_id=uuid4())

    for span in observability.tracer.spans:
        for value in span.attributes.values():
            assert not isinstance(value, bytes)
            assert _DIGEST not in str(value)


class FakeIngestionRepository:
    def __init__(self, *, reaped: int = 0, rowcount: int = 1) -> None:
        self._reaped = reaped
        self._rowcount = rowcount
        self.mark_failed_calls: list[str] = []
        self.release_calls: list[str] = []

    async def fail_exhausted_expired_items(self, *, now: datetime, max_attempts: int) -> int:
        return self._reaped

    async def mark_failed(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        now: datetime,
        error_code: str,
        error_message: str | None,
        execution_metadata: dict[str, object] | None,
    ) -> int:
        self.mark_failed_calls.append(error_code)
        return self._rowcount

    async def release_for_retry(
        self,
        *,
        item_id: UUID,
        attempt_number: int,
        error_code: str,
        error_message: str | None,
    ) -> int:
        self.release_calls.append(error_code)
        return self._rowcount


class FakeOutbox:
    async def enqueue(self, **kwargs: object) -> None:
        return None

    async def discard_pending_for_aggregate(self, **kwargs: object) -> int:
        return 1


class FakeIngestionUnitOfWork:
    def __init__(self, repository: FakeIngestionRepository) -> None:
        self.ingestion = repository
        self.outbox = FakeOutbox()

    async def __aenter__(self) -> "FakeIngestionUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None


def make_lifecycle(repository: FakeIngestionRepository) -> IngestionLifecycleService:
    def factory() -> IngestionUnitOfWork:
        return FakeIngestionUnitOfWork(repository)  # type: ignore[return-value]

    return IngestionLifecycleService(
        factory,
        lease_duration=timedelta(seconds=60),
        max_attempts=3,
        clock=lambda: _NOW,
    )


async def test_scheduling_a_retry_emits_the_retry_span(
    observability: ObservabilityHarness,
) -> None:
    repository = FakeIngestionRepository()
    lifecycle = make_lifecycle(repository)

    with ingestion_job_context(job_type=JobType.PROCESS_INGESTION_ITEM.value):
        await lifecycle.schedule_retry(
            item_id=uuid4(),
            attempt_number=1,
            error_code="transient_ingestion_error",
        )

    span = observability.tracer.find(SpanName.INGESTION_RETRY)[0]
    assert span.attributes["attempts_exhausted"] is False
    assert repository.release_calls == ["transient_ingestion_error"]


async def test_exhausting_attempts_counts_a_terminal_failure(
    observability: ObservabilityHarness,
) -> None:
    repository = FakeIngestionRepository()
    lifecycle = make_lifecycle(repository)

    with ingestion_job_context(job_type=JobType.PROCESS_INGESTION_ITEM.value):
        await lifecycle.schedule_retry(
            item_id=uuid4(),
            attempt_number=3,
            error_code="transient_ingestion_error",
        )

    assert repository.mark_failed_calls == ["max_attempts_exceeded"]
    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_JOBS_FAILED_TOTAL,
            labels={
                LabelKey.JOB_TYPE: JobType.PROCESS_INGESTION_ITEM.value,
                LabelKey.LANGUAGE: "unknown",
                LabelKey.STAGE: JobStage.RETRY.value,
                LabelKey.ERROR_CODE: "max_attempts_exceeded",
            },
        )
        == 1
    )


async def test_recovery_emits_its_span_and_counts_reclaimed_items(
    observability: ObservabilityHarness,
) -> None:
    lifecycle = make_lifecycle(FakeIngestionRepository(reaped=4))

    reaped = await lifecycle.reap_expired_items()

    assert reaped == 4
    span = observability.tracer.find(SpanName.INGESTION_RECOVERY)[0]
    assert span.attributes["reaped_items"] == 4
    assert (
        observability.metrics.counter_value(
            MetricName.INGESTION_RECOVERED_TOTAL,
            labels={
                LabelKey.JOB_TYPE: JobType.PROCESS_INGESTION_ITEM.value,
                LabelKey.STATUS: "max_attempts_exceeded",
            },
        )
        == 4
    )


async def test_recovery_with_nothing_to_reap_records_no_counter(
    observability: ObservabilityHarness,
) -> None:
    lifecycle = make_lifecycle(FakeIngestionRepository(reaped=0))

    assert await lifecycle.reap_expired_items() == 0
    assert observability.metrics.snapshot() == ()
