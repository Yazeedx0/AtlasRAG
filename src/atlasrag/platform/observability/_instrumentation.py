import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import ExitStack, asynccontextmanager, contextmanager

import structlog

from atlasrag.contracts.observability import Span, SpanAttributeValue
from atlasrag.contracts.types.observability import (
    ErrorCategory,
    JobStage,
    LabelKey,
    LanguageLabel,
    MetricName,
    OutcomeLabel,
    SpanName,
    SpanStatus,
)
from atlasrag.platform.observability._cardinality import (
    categorize_error_code,
    categorize_exception,
    normalize_language,
)
from atlasrag.platform.observability._context import (
    current_job_type,
    current_language,
    job_stage,
    sync_log_context,
)
from atlasrag.platform.observability._registry import get_metrics, get_tracer

_logger = structlog.get_logger(__name__)


def _guard[Result](operation: str, action: Callable[[], Result]) -> Result | None:
    try:
        return action()
    except Exception as error:
        _logger.warning(
            "observability_operation_failed",
            operation=operation,
            error_type=type(error).__name__,
        )
        return None


def increment(
    name: MetricName,
    *,
    labels: Mapping[LabelKey, str] | None = None,
    value: float = 1.0,
) -> None:
    _guard(name.value, lambda: get_metrics().increment(name, labels=labels, value=value))
    return None


def observe(
    name: MetricName,
    value: float,
    *,
    labels: Mapping[LabelKey, str] | None = None,
) -> None:
    _guard(name.value, lambda: get_metrics().observe(name, value, labels=labels))
    return None


def set_gauge(
    name: MetricName,
    value: float,
    *,
    labels: Mapping[LabelKey, str] | None = None,
) -> None:
    _guard(name.value, lambda: get_metrics().set_gauge(name, value, labels=labels))
    return None


class StageObservation:
    def __init__(self, *, span: Span | None, labels: dict[LabelKey, str]) -> None:
        self._span = span
        self._labels = labels
        self._status: OutcomeLabel = OutcomeLabel.SUCCESS
        self._error_category: ErrorCategory | None = None

    @property
    def span(self) -> Span | None:
        return self._span

    @property
    def labels(self) -> Mapping[LabelKey, str]:
        return dict(self._labels)

    @property
    def status(self) -> OutcomeLabel:
        return self._status

    @property
    def error_category(self) -> ErrorCategory | None:
        return self._error_category

    def set_attribute(self, key: str, value: SpanAttributeValue) -> None:
        span = self._span
        if span is not None:
            _guard("span.set_attribute", lambda: span.set_attribute(key, value))
        return None

    def set_label(self, key: LabelKey, value: str) -> None:
        self._labels[key] = value
        span = self._span
        if span is not None:
            _guard("span.set_label", lambda: span.set_label(key, value))
        return None

    def set_status(self, status: OutcomeLabel) -> None:
        self._status = status
        return None

    def record_error(self, category: ErrorCategory) -> None:
        self._error_category = category
        self._status = OutcomeLabel.FAILURE
        span = self._span
        if span is not None:
            _guard("span.record_error", lambda: span.record_error(error_code=category.value))
        return None


@contextmanager
def _optional_span(
    name: SpanName,
    attributes: Mapping[str, SpanAttributeValue] | None,
) -> Iterator[Span | None]:
    with ExitStack() as stack:
        try:
            span = stack.enter_context(get_tracer().start_span(name, attributes=attributes))
        except Exception as error:
            _logger.warning(
                "observability_span_failed",
                span_name=name.value,
                error_type=type(error).__name__,
            )
            yield None
            return
        yield span


@contextmanager
def traced_stage_sync(
    name: SpanName,
    *,
    stage: JobStage | None = None,
    duration_metric: MetricName | None = None,
    labels: Mapping[LabelKey, str] | None = None,
    attributes: Mapping[str, SpanAttributeValue] | None = None,
    with_language: bool = True,
) -> Iterator[StageObservation]:
    started = time.perf_counter()
    with ExitStack() as stack:
        if stage is not None:
            stack.enter_context(job_stage(stage))
        span = stack.enter_context(_optional_span(name, attributes))
        observation = StageObservation(span=span, labels=dict(labels or {}))
        try:
            yield observation
        except Exception as error:
            observation.record_error(categorize_exception(error))
            raise
        finally:
            sync_log_context()
            _record_stage_duration(
                observation=observation,
                duration_metric=duration_metric,
                duration_seconds=time.perf_counter() - started,
                with_language=with_language,
            )


@asynccontextmanager
async def traced_stage(
    name: SpanName,
    *,
    stage: JobStage | None = None,
    duration_metric: MetricName | None = None,
    labels: Mapping[LabelKey, str] | None = None,
    attributes: Mapping[str, SpanAttributeValue] | None = None,
    with_language: bool = True,
) -> AsyncIterator[StageObservation]:
    with traced_stage_sync(
        name,
        stage=stage,
        duration_metric=duration_metric,
        labels=labels,
        attributes=attributes,
        with_language=with_language,
    ) as observation:
        yield observation


def _record_stage_duration(
    *,
    observation: StageObservation,
    duration_metric: MetricName | None,
    duration_seconds: float,
    with_language: bool,
) -> None:
    if duration_metric is None:
        return None

    labels = dict(observation.labels)
    labels[LabelKey.STATUS] = observation.status.value
    if with_language and LabelKey.LANGUAGE not in labels:
        labels[LabelKey.LANGUAGE] = current_language().value
    labels.pop(LabelKey.ERROR_CODE, None)
    labels.pop(LabelKey.FALLBACK_REASON, None)
    observe(duration_metric, duration_seconds, labels=labels)
    return None


def annotate_span(span: Span | None, **attributes: SpanAttributeValue) -> None:
    if span is None:
        return None
    try:
        for key, value in attributes.items():
            span.set_attribute(key, value)
    except Exception as error:
        _logger.warning(
            "observability_operation_failed",
            operation="span.set_attribute",
            error_type=type(error).__name__,
        )
    return None


def mark_span_status(span: Span | None, status: SpanStatus) -> None:
    if span is None:
        return None
    _guard("span.set_status", lambda: span.set_status(status))
    return None


def record_job_started(*, job_type: str) -> None:
    increment(MetricName.INGESTION_JOBS_STARTED_TOTAL, labels={LabelKey.JOB_TYPE: job_type})
    return None


def record_job_completed(*, job_type: str, extractor_method: str) -> None:
    increment(
        MetricName.INGESTION_JOBS_COMPLETED_TOTAL,
        labels={
            LabelKey.JOB_TYPE: job_type,
            LabelKey.LANGUAGE: current_language().value,
            LabelKey.EXTRACTOR_METHOD: extractor_method,
        },
    )
    return None


def record_job_failed(*, job_type: str, stage: JobStage, error_code: str | None) -> None:
    increment(
        MetricName.INGESTION_JOBS_FAILED_TOTAL,
        labels={
            LabelKey.JOB_TYPE: job_type,
            LabelKey.LANGUAGE: current_language().value,
            LabelKey.STAGE: stage.value,
            LabelKey.ERROR_CODE: categorize_error_code(error_code).value,
        },
    )
    return None


def record_retry(*, job_type: str, stage: JobStage, error_code: str | None) -> None:
    increment(
        MetricName.INGESTION_RETRIES_TOTAL,
        labels={
            LabelKey.JOB_TYPE: job_type,
            LabelKey.STAGE: stage.value,
            LabelKey.ERROR_CODE: categorize_error_code(error_code).value,
        },
    )
    return None


def record_lease_lost(*, job_type: str, stage: JobStage) -> None:
    increment(
        MetricName.INGESTION_LEASE_LOST_TOTAL,
        labels={LabelKey.JOB_TYPE: job_type, LabelKey.STAGE: stage.value},
    )
    return None


def record_recovered(*, job_type: str, status: str, count: int) -> None:
    if count <= 0:
        return None
    increment(
        MetricName.INGESTION_RECOVERED_TOTAL,
        labels={LabelKey.JOB_TYPE: job_type, LabelKey.STATUS: status},
        value=float(count),
    )
    return None


def record_extraction_primary_success(*, extractor_method: str) -> None:
    increment(
        MetricName.EXTRACTION_PRIMARY_SUCCESS_TOTAL,
        labels={
            LabelKey.LANGUAGE: current_language().value,
            LabelKey.EXTRACTOR_METHOD: extractor_method,
        },
    )
    return None


def record_extraction_fallback(*, extractor_method: str, fallback_reason: str | None) -> None:
    increment(
        MetricName.EXTRACTION_FALLBACK_TOTAL,
        labels={
            LabelKey.LANGUAGE: current_language().value,
            LabelKey.EXTRACTOR_METHOD: extractor_method,
            LabelKey.FALLBACK_REASON: categorize_error_code(fallback_reason).value,
        },
    )
    return None


def record_extraction_failure(*, error_code: str | None, retryable: bool) -> None:
    increment(
        MetricName.EXTRACTION_FAILURES_TOTAL,
        labels={
            LabelKey.LANGUAGE: current_language().value,
            LabelKey.ERROR_CODE: categorize_error_code(error_code).value,
            LabelKey.RETRYABLE: str(retryable).lower(),
        },
    )
    return None


def record_blocks_per_document(*, block_count: int, extractor_method: str) -> None:
    observe(
        MetricName.EXTRACTION_BLOCKS_PER_DOCUMENT,
        float(block_count),
        labels={
            LabelKey.LANGUAGE: current_language().value,
            LabelKey.EXTRACTOR_METHOD: extractor_method,
        },
    )
    return None


def record_chunks_per_document(*, chunk_count: int, language_code: str | None = None) -> None:
    language = current_language() if language_code is None else normalize_language(language_code)
    observe(
        MetricName.CHUNKS_PER_DOCUMENT,
        float(chunk_count),
        labels={LabelKey.LANGUAGE: language.value},
    )
    return None


def record_outbox_attempt(*, job_type: str) -> None:
    increment(MetricName.OUTBOX_PUBLISH_ATTEMPTS_TOTAL, labels={LabelKey.JOB_TYPE: job_type})
    return None


def record_outbox_success(*, job_type: str) -> None:
    increment(MetricName.OUTBOX_PUBLISH_SUCCESS_TOTAL, labels={LabelKey.JOB_TYPE: job_type})
    return None


def record_outbox_failure(*, job_type: str, error_code: str | None) -> None:
    increment(
        MetricName.OUTBOX_PUBLISH_FAILURE_TOTAL,
        labels={
            LabelKey.JOB_TYPE: job_type,
            LabelKey.ERROR_CODE: categorize_error_code(error_code).value,
        },
    )
    return None


def record_outbox_backlog(*, pending: Mapping[str, int]) -> None:
    for job_type, count in pending.items():
        set_gauge(
            MetricName.OUTBOX_PENDING_JOBS,
            float(count),
            labels={LabelKey.JOB_TYPE: job_type},
        )
    return None


def normalized_language_label(language_code: str | None) -> LanguageLabel:
    return normalize_language(language_code)


def job_type_label() -> str:
    return current_job_type()


__all__ = [
    "StageObservation",
    "annotate_span",
    "increment",
    "job_type_label",
    "mark_span_status",
    "normalized_language_label",
    "observe",
    "record_blocks_per_document",
    "record_chunks_per_document",
    "record_extraction_failure",
    "record_extraction_fallback",
    "record_extraction_primary_success",
    "record_job_completed",
    "record_job_failed",
    "record_job_started",
    "record_lease_lost",
    "record_outbox_attempt",
    "record_outbox_backlog",
    "record_outbox_failure",
    "record_outbox_success",
    "record_recovered",
    "record_retry",
    "set_gauge",
    "traced_stage",
    "traced_stage_sync",
]
