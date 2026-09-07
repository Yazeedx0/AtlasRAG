from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class SpanName(StrEnum):
    INGESTION_JOB = "ingestion.job"
    INGESTION_CLAIM = "ingestion.claim"
    ARTIFACT_LOAD = "ingestion.artifact.load"
    ARTIFACT_INTEGRITY = "ingestion.artifact.integrity"
    EXTRACTION = "ingestion.extraction"
    EXTRACTION_PRIMARY_OCR = "ingestion.extraction.primary_ocr"
    EXTRACTION_FALLBACK_VLM = "ingestion.extraction.fallback_vlm"
    EXTRACTION_QUALITY_GATE = "ingestion.extraction.quality_gate"
    CHUNKING = "ingestion.chunking"
    PERSISTENCE = "ingestion.persistence"
    INGESTION_RETRY = "ingestion.retry"
    INGESTION_RECOVERY = "ingestion.recovery"
    OUTBOX_CLAIM = "outbox.claim"
    OUTBOX_PUBLISH = "outbox.publish"
    OUTBOX_MARK_PUBLISHED = "outbox.mark_published"
    WORKER_TASK = "worker.task"


class JobStage(StrEnum):
    CLAIM = "claim"
    ARTIFACT_LOAD = "artifact_load"
    ARTIFACT_INTEGRITY = "artifact_integrity"
    EXTRACTION = "extraction"
    QUALITY_GATE = "quality_gate"
    CHUNKING = "chunking"
    PERSISTENCE = "persistence"
    RETRY = "retry"
    RECOVERY = "recovery"
    OUTBOX_PUBLISH = "outbox_publish"
    UNKNOWN = "unknown"


class SpanStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class MetricKind(StrEnum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class MetricName(StrEnum):
    INGESTION_JOBS_STARTED_TOTAL = "ingestion_jobs_started_total"
    INGESTION_JOBS_COMPLETED_TOTAL = "ingestion_jobs_completed_total"
    INGESTION_JOBS_FAILED_TOTAL = "ingestion_jobs_failed_total"
    INGESTION_RETRIES_TOTAL = "ingestion_retries_total"
    INGESTION_LEASE_LOST_TOTAL = "ingestion_lease_lost_total"
    INGESTION_RECOVERED_TOTAL = "ingestion_recovered_total"

    OUTBOX_PUBLISH_SUCCESS_TOTAL = "outbox_publish_success_total"
    OUTBOX_PUBLISH_FAILURE_TOTAL = "outbox_publish_failure_total"
    OUTBOX_PUBLISH_ATTEMPTS_TOTAL = "outbox_publish_attempts_total"
    OUTBOX_PENDING_JOBS = "outbox_pending_jobs"

    EXTRACTION_PRIMARY_SUCCESS_TOTAL = "extraction_primary_success_total"
    EXTRACTION_FALLBACK_TOTAL = "extraction_fallback_total"
    EXTRACTION_FAILURES_TOTAL = "extraction_failures_total"

    INGESTION_DURATION_SECONDS = "ingestion_duration_seconds"
    ARTIFACT_LOAD_DURATION_SECONDS = "artifact_load_duration_seconds"
    EXTRACTION_DURATION_SECONDS = "extraction_duration_seconds"
    CHUNKING_DURATION_SECONDS = "chunking_duration_seconds"
    PERSISTENCE_DURATION_SECONDS = "persistence_duration_seconds"

    CHUNKS_PER_DOCUMENT = "chunks_per_document"
    EXTRACTION_BLOCKS_PER_DOCUMENT = "extraction_blocks_per_document"

    WORKER_TASKS_STARTED_TOTAL = "worker_tasks_started_total"
    WORKER_TASKS_COMPLETED_TOTAL = "worker_tasks_completed_total"
    WORKER_TASKS_FAILED_TOTAL = "worker_tasks_failed_total"
    WORKER_TASK_RETRIES_TOTAL = "worker_task_retries_total"
    WORKER_TASK_DURATION_SECONDS = "worker_task_duration_seconds"


class LabelKey(StrEnum):
    STATUS = "status"
    STAGE = "stage"
    LANGUAGE = "language"
    EXTRACTOR_METHOD = "extractor_method"
    FALLBACK_REASON = "fallback_reason"
    ERROR_CODE = "error_code"
    JOB_TYPE = "job_type"
    TASK_NAME = "task_name"
    QUEUE = "queue"
    RETRYABLE = "retryable"


class LanguageLabel(StrEnum):
    ARABIC = "ar"
    ENGLISH = "en"
    OTHER = "other"
    UNKNOWN = "unknown"


class OutcomeLabel(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    LEASE_LOST = "lease_lost"
    RETRY = "retry"
    NOT_CLAIMED = "not_claimed"


class ErrorCategory(StrEnum):
    ARTIFACT_UNAVAILABLE = "artifact_unavailable"
    ARTIFACT_INTEGRITY = "artifact_integrity"
    ARTIFACT_MISSING = "artifact_missing"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    EXTRACTION_FAILED = "extraction_failed"
    LEASE_LOST = "lease_lost"
    MAX_ATTEMPTS_EXCEEDED = "max_attempts_exceeded"
    UNKNOWN_JOB_TYPE = "unknown_job_type"
    DISPATCH_FAILED = "dispatch_failed"
    SUPERSEDED_BY_RETRY = "superseded_by_retry"
    TRANSIENT = "transient"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: MetricName
    kind: MetricKind
    description: str
    labels: frozenset[LabelKey]


@dataclass(frozen=True, slots=True)
class MetricSample:
    name: str
    kind: MetricKind
    labels: Mapping[str, str]
    value: float
    count: int


@dataclass(frozen=True, slots=True)
class RecordedSpan:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    status: SpanStatus
    duration_seconds: float
    attributes: Mapping[str, str | int | float | bool] = field(default_factory=dict)


__all__ = [
    "ErrorCategory",
    "JobStage",
    "LabelKey",
    "LanguageLabel",
    "MetricDefinition",
    "MetricKind",
    "MetricName",
    "MetricSample",
    "OutcomeLabel",
    "RecordedSpan",
    "SpanName",
    "SpanStatus",
]
