from collections.abc import Mapping

from atlasrag.contracts.types.observability import (
    ErrorCategory,
    LabelKey,
    LanguageLabel,
    MetricDefinition,
    MetricKind,
    MetricName,
)

MAX_SERIES_PER_METRIC = 200
MAX_LABEL_VALUE_LENGTH = 48

FORBIDDEN_LABEL_KEYS: frozenset[str] = frozenset(
    {
        "aggregate_id",
        "artifact_id",
        "canonical_key",
        "correlation_id",
        "document_artifact_id",
        "document_id",
        "document_version_id",
        "error_message",
        "exception",
        "file_hash",
        "ingestion_item_id",
        "ingestion_run_id",
        "job_id",
        "message",
        "observed_file_hash",
        "payload",
        "principal_id",
        "source_name",
        "source_uri",
        "span_id",
        "storage_key",
        "task_id",
        "trace_id",
        "user_id",
    }
)

_COUNTER = MetricKind.COUNTER
_GAUGE = MetricKind.GAUGE
_HISTOGRAM = MetricKind.HISTOGRAM


def _definition(
    name: MetricName,
    kind: MetricKind,
    description: str,
    *labels: LabelKey,
) -> MetricDefinition:
    return MetricDefinition(
        name=name,
        kind=kind,
        description=description,
        labels=frozenset(labels),
    )


METRIC_DEFINITIONS: Mapping[MetricName, MetricDefinition] = {
    definition.name: definition
    for definition in (
        _definition(
            MetricName.INGESTION_JOBS_STARTED_TOTAL,
            _COUNTER,
            "Ingestion attempts that acquired a lease.",
            LabelKey.JOB_TYPE,
        ),
        _definition(
            MetricName.INGESTION_JOBS_COMPLETED_TOTAL,
            _COUNTER,
            "Ingestion attempts that reached a terminal success.",
            LabelKey.JOB_TYPE,
            LabelKey.LANGUAGE,
            LabelKey.EXTRACTOR_METHOD,
        ),
        _definition(
            MetricName.INGESTION_JOBS_FAILED_TOTAL,
            _COUNTER,
            "Ingestion attempts that reached a terminal failure.",
            LabelKey.JOB_TYPE,
            LabelKey.LANGUAGE,
            LabelKey.STAGE,
            LabelKey.ERROR_CODE,
        ),
        _definition(
            MetricName.INGESTION_RETRIES_TOTAL,
            _COUNTER,
            "Ingestion attempts released back to the queue for another try.",
            LabelKey.JOB_TYPE,
            LabelKey.STAGE,
            LabelKey.ERROR_CODE,
        ),
        _definition(
            MetricName.INGESTION_LEASE_LOST_TOTAL,
            _COUNTER,
            "Ingestion attempts abandoned because the worker no longer owned the lease.",
            LabelKey.JOB_TYPE,
            LabelKey.STAGE,
        ),
        _definition(
            MetricName.INGESTION_RECOVERED_TOTAL,
            _COUNTER,
            "Expired ingestion leases reclaimed by the recovery sweep.",
            LabelKey.JOB_TYPE,
            LabelKey.STATUS,
        ),
        _definition(
            MetricName.OUTBOX_PUBLISH_SUCCESS_TOTAL,
            _COUNTER,
            "Outbox rows confirmed published to the broker.",
            LabelKey.JOB_TYPE,
        ),
        _definition(
            MetricName.OUTBOX_PUBLISH_FAILURE_TOTAL,
            _COUNTER,
            "Outbox rows that could not be published.",
            LabelKey.JOB_TYPE,
            LabelKey.ERROR_CODE,
        ),
        _definition(
            MetricName.OUTBOX_PUBLISH_ATTEMPTS_TOTAL,
            _COUNTER,
            "Outbox rows claimed for a publish attempt.",
            LabelKey.JOB_TYPE,
        ),
        _definition(
            MetricName.OUTBOX_PENDING_JOBS,
            _GAUGE,
            "Outbox rows waiting to be published.",
            LabelKey.JOB_TYPE,
        ),
        _definition(
            MetricName.EXTRACTION_PRIMARY_SUCCESS_TOTAL,
            _COUNTER,
            "Documents extracted without needing the fallback extractor.",
            LabelKey.LANGUAGE,
            LabelKey.EXTRACTOR_METHOD,
        ),
        _definition(
            MetricName.EXTRACTION_FALLBACK_TOTAL,
            _COUNTER,
            "Documents extracted by the fallback extractor.",
            LabelKey.LANGUAGE,
            LabelKey.EXTRACTOR_METHOD,
            LabelKey.FALLBACK_REASON,
        ),
        _definition(
            MetricName.EXTRACTION_FAILURES_TOTAL,
            _COUNTER,
            "Documents that no extractor could process.",
            LabelKey.LANGUAGE,
            LabelKey.ERROR_CODE,
            LabelKey.RETRYABLE,
        ),
        _definition(
            MetricName.INGESTION_DURATION_SECONDS,
            _HISTOGRAM,
            "Wall-clock duration of a claimed ingestion attempt.",
            LabelKey.JOB_TYPE,
            LabelKey.LANGUAGE,
            LabelKey.STATUS,
        ),
        _definition(
            MetricName.ARTIFACT_LOAD_DURATION_SECONDS,
            _HISTOGRAM,
            "Duration of artifact retrieval and integrity verification.",
            LabelKey.LANGUAGE,
            LabelKey.STATUS,
        ),
        _definition(
            MetricName.EXTRACTION_DURATION_SECONDS,
            _HISTOGRAM,
            "Duration of the extraction stage including fallback.",
            LabelKey.LANGUAGE,
            LabelKey.EXTRACTOR_METHOD,
            LabelKey.STATUS,
        ),
        _definition(
            MetricName.CHUNKING_DURATION_SECONDS,
            _HISTOGRAM,
            "Duration of the chunking stage.",
            LabelKey.LANGUAGE,
            LabelKey.STATUS,
        ),
        _definition(
            MetricName.PERSISTENCE_DURATION_SECONDS,
            _HISTOGRAM,
            "Duration of the terminal persistence stage.",
            LabelKey.LANGUAGE,
            LabelKey.STATUS,
        ),
        _definition(
            MetricName.CHUNKS_PER_DOCUMENT,
            _HISTOGRAM,
            "Chunks produced per ingested document.",
            LabelKey.LANGUAGE,
        ),
        _definition(
            MetricName.EXTRACTION_BLOCKS_PER_DOCUMENT,
            _HISTOGRAM,
            "Extracted blocks produced per ingested document.",
            LabelKey.LANGUAGE,
            LabelKey.EXTRACTOR_METHOD,
        ),
        _definition(
            MetricName.WORKER_TASKS_STARTED_TOTAL,
            _COUNTER,
            "Celery tasks that entered execution.",
            LabelKey.TASK_NAME,
            LabelKey.QUEUE,
        ),
        _definition(
            MetricName.WORKER_TASKS_COMPLETED_TOTAL,
            _COUNTER,
            "Celery tasks that returned without raising.",
            LabelKey.TASK_NAME,
            LabelKey.QUEUE,
        ),
        _definition(
            MetricName.WORKER_TASKS_FAILED_TOTAL,
            _COUNTER,
            "Celery tasks that raised out of the task body.",
            LabelKey.TASK_NAME,
            LabelKey.QUEUE,
            LabelKey.ERROR_CODE,
        ),
        _definition(
            MetricName.WORKER_TASK_RETRIES_TOTAL,
            _COUNTER,
            "Celery task retries requested by the broker runtime.",
            LabelKey.TASK_NAME,
            LabelKey.QUEUE,
        ),
        _definition(
            MetricName.WORKER_TASK_DURATION_SECONDS,
            _HISTOGRAM,
            "Wall-clock duration of a Celery task body.",
            LabelKey.TASK_NAME,
            LabelKey.QUEUE,
            LabelKey.STATUS,
        ),
    )
}


class MetricCardinalityError(Exception):
    """A metric was recorded with labels the cardinality policy forbids."""


_ERROR_CATEGORY_BY_CODE: Mapping[str, ErrorCategory] = {
    "artifact_unavailable_for_ingestion": ErrorCategory.ARTIFACT_UNAVAILABLE,
    "artifact_integrity_mismatch": ErrorCategory.ARTIFACT_INTEGRITY,
    "artifact_object_missing": ErrorCategory.ARTIFACT_MISSING,
    "extraction_failed": ErrorCategory.EXTRACTION_FAILED,
    "max_attempts_exceeded": ErrorCategory.MAX_ATTEMPTS_EXCEEDED,
    "unknown_job_type": ErrorCategory.UNKNOWN_JOB_TYPE,
    "superseded_by_retry": ErrorCategory.SUPERSEDED_BY_RETRY,
    "transient_ingestion_error": ErrorCategory.TRANSIENT,
    "unexpected_ingestion_error": ErrorCategory.OTHER,
    "lease_lost": ErrorCategory.LEASE_LOST,
}

_KNOWN_ERROR_CATEGORIES: frozenset[str] = frozenset(member.value for member in ErrorCategory)


def categorize_error_code(error_code: str | None) -> ErrorCategory:
    if error_code is None:
        return ErrorCategory.OTHER
    normalized = error_code.strip().lower()
    if normalized in _ERROR_CATEGORY_BY_CODE:
        return _ERROR_CATEGORY_BY_CODE[normalized]
    if normalized in _KNOWN_ERROR_CATEGORIES:
        return ErrorCategory(normalized)
    prefix = normalized.split(":", 1)[0]
    if prefix in _ERROR_CATEGORY_BY_CODE:
        return _ERROR_CATEGORY_BY_CODE[prefix]
    if prefix in _KNOWN_ERROR_CATEGORIES:
        return ErrorCategory(prefix)
    return ErrorCategory.OTHER


def categorize_exception(error: BaseException) -> ErrorCategory:
    if isinstance(error, TimeoutError):
        return ErrorCategory.TIMEOUT
    return categorize_error_code(type(error).__name__)


def normalize_language(language_code: str | None) -> LanguageLabel:
    if language_code is None:
        return LanguageLabel.UNKNOWN
    normalized = language_code.strip().lower()
    if not normalized:
        return LanguageLabel.UNKNOWN
    primary = normalized.replace("_", "-").split("-", 1)[0]
    if primary == LanguageLabel.ARABIC.value:
        return LanguageLabel.ARABIC
    if primary == LanguageLabel.ENGLISH.value:
        return LanguageLabel.ENGLISH
    return LanguageLabel.OTHER


def validate_labels(
    name: MetricName,
    labels: Mapping[LabelKey, str] | None,
) -> dict[str, str]:
    definition = METRIC_DEFINITIONS.get(name)
    if definition is None:
        raise MetricCardinalityError(f"Metric {name.value!r} has no cardinality definition.")

    validated: dict[str, str] = {}
    for key, value in (labels or {}).items():
        label_key = key.value if isinstance(key, LabelKey) else str(key)
        if label_key in FORBIDDEN_LABEL_KEYS:
            raise MetricCardinalityError(
                f"Label {label_key!r} is a high-cardinality identifier and cannot label metrics."
            )
        if not isinstance(key, LabelKey):
            raise MetricCardinalityError(
                f"Label {label_key!r} is not a declared low-cardinality label key."
            )
        if key not in definition.labels:
            raise MetricCardinalityError(
                f"Label {label_key!r} is not declared for metric {name.value!r}."
            )
        if len(value) > MAX_LABEL_VALUE_LENGTH:
            raise MetricCardinalityError(
                f"Label {label_key!r} value exceeds {MAX_LABEL_VALUE_LENGTH} characters."
            )
        validated[label_key] = value

    missing = {label.value for label in definition.labels} - set(validated)
    if missing:
        raise MetricCardinalityError(
            f"Metric {name.value!r} is missing declared labels: {sorted(missing)}."
        )
    return validated


__all__ = [
    "FORBIDDEN_LABEL_KEYS",
    "MAX_LABEL_VALUE_LENGTH",
    "MAX_SERIES_PER_METRIC",
    "METRIC_DEFINITIONS",
    "MetricCardinalityError",
    "categorize_error_code",
    "categorize_exception",
    "normalize_language",
    "validate_labels",
]
