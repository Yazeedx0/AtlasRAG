import pytest

from atlasrag.contracts.types.observability import (
    ErrorCategory,
    LabelKey,
    LanguageLabel,
    MetricName,
)
from atlasrag.platform.observability import (
    FORBIDDEN_LABEL_KEYS,
    METRIC_DEFINITIONS,
    InMemoryMetricsRecorder,
    MetricCardinalityError,
    categorize_error_code,
    normalize_language,
    validate_labels,
)

pytestmark = pytest.mark.unit

_HIGH_CARDINALITY_KEYS = (
    "document_id",
    "artifact_id",
    "ingestion_item_id",
    "ingestion_run_id",
    "user_id",
    "principal_id",
    "task_id",
    "trace_id",
    "error_message",
)


@pytest.mark.parametrize("key", _HIGH_CARDINALITY_KEYS)
def test_high_cardinality_identifiers_are_forbidden_label_keys(key: str) -> None:
    assert key in FORBIDDEN_LABEL_KEYS


@pytest.mark.parametrize("key", _HIGH_CARDINALITY_KEYS)
def test_no_metric_declares_a_high_cardinality_label(key: str) -> None:
    declared = {
        label.value for definition in METRIC_DEFINITIONS.values() for label in definition.labels
    }

    assert key not in declared


def test_every_metric_name_has_a_definition() -> None:
    assert set(METRIC_DEFINITIONS) == set(MetricName)


def test_recording_with_a_forbidden_label_is_rejected() -> None:
    recorder = InMemoryMetricsRecorder()

    with pytest.raises(MetricCardinalityError):
        recorder.increment(
            MetricName.INGESTION_JOBS_STARTED_TOTAL,
            labels={"artifact_id": "b0a1"},  # type: ignore[dict-item]
        )


def test_recording_with_an_undeclared_label_is_rejected() -> None:
    recorder = InMemoryMetricsRecorder()

    with pytest.raises(MetricCardinalityError):
        recorder.increment(
            MetricName.INGESTION_JOBS_STARTED_TOTAL,
            labels={LabelKey.FALLBACK_REASON: "timeout"},
        )


def test_recording_a_counter_as_a_histogram_is_rejected() -> None:
    recorder = InMemoryMetricsRecorder()

    with pytest.raises(MetricCardinalityError):
        recorder.observe(MetricName.INGESTION_JOBS_STARTED_TOTAL, 1.0)


def test_oversized_label_values_are_rejected() -> None:
    with pytest.raises(MetricCardinalityError):
        validate_labels(
            MetricName.INGESTION_JOBS_STARTED_TOTAL,
            {LabelKey.JOB_TYPE: "j" * 200},
        )


def test_series_growth_is_capped_per_metric() -> None:
    recorder = InMemoryMetricsRecorder(max_series_per_metric=2)

    for index in range(5):
        recorder.increment(
            MetricName.INGESTION_JOBS_STARTED_TOTAL,
            labels={LabelKey.JOB_TYPE: f"type-{index}"},
        )

    assert len(recorder.snapshot()) == 2
    assert recorder.dropped_series(MetricName.INGESTION_JOBS_STARTED_TOTAL) == 3


@pytest.mark.parametrize(
    ("error_code", "expected"),
    [
        ("artifact_integrity_mismatch", ErrorCategory.ARTIFACT_INTEGRITY),
        ("artifact_unavailable_for_ingestion", ErrorCategory.ARTIFACT_UNAVAILABLE),
        ("max_attempts_exceeded", ErrorCategory.MAX_ATTEMPTS_EXCEEDED),
        ("dispatch_failed:ConnectionResetError", ErrorCategory.DISPATCH_FAILED),
        ("TimeoutError", ErrorCategory.OTHER),
        (None, ErrorCategory.OTHER),
    ],
)
def test_error_codes_collapse_into_bounded_categories(
    error_code: str | None,
    expected: ErrorCategory,
) -> None:
    assert categorize_error_code(error_code) is expected


def test_unbounded_error_text_collapses_to_a_single_category() -> None:
    categories = {
        categorize_error_code(f"connection to host-{index} refused at 10.0.0.{index}")
        for index in range(100)
    }

    assert categories == {ErrorCategory.OTHER}


@pytest.mark.parametrize(
    ("language_code", "expected"),
    [
        ("ar", LanguageLabel.ARABIC),
        ("AR-SA", LanguageLabel.ARABIC),
        ("en", LanguageLabel.ENGLISH),
        ("en_US", LanguageLabel.ENGLISH),
        ("fr", LanguageLabel.OTHER),
        ("", LanguageLabel.UNKNOWN),
        (None, LanguageLabel.UNKNOWN),
    ],
)
def test_language_normalizes_to_a_bounded_set(
    language_code: str | None,
    expected: LanguageLabel,
) -> None:
    assert normalize_language(language_code) is expected
