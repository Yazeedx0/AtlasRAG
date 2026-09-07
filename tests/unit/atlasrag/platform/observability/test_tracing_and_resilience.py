import pytest
from tests.unit.conftest import ObservabilityHarness

from atlasrag.contracts.types.observability import (
    JobStage,
    LabelKey,
    MetricName,
    SpanName,
    SpanStatus,
)
from atlasrag.platform.observability import (
    InMemoryTracer,
    NullMetricsRecorder,
    NullTracer,
    failed_stage,
    ingestion_job_context,
    record_job_started,
    set_metrics,
    set_tracer,
    traced_stage,
    traced_stage_sync,
    update_job_context,
)

pytestmark = pytest.mark.unit


class ExplodingTracer:
    def start_span(self, name: SpanName, *, attributes: object = None) -> object:
        raise RuntimeError("tracing backend is down")


class ExplodingMetrics:
    def increment(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("metrics backend is down")

    def observe(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("metrics backend is down")

    def set_gauge(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("metrics backend is down")


async def test_nested_spans_share_a_trace_and_link_to_their_parent(
    observability: ObservabilityHarness,
) -> None:
    async with (
        traced_stage(SpanName.INGESTION_JOB),
        traced_stage(SpanName.EXTRACTION, stage=JobStage.EXTRACTION),
        traced_stage(SpanName.EXTRACTION_PRIMARY_OCR),
    ):
        pass

    spans = observability.tracer.spans
    ocr, extraction, job = spans

    assert observability.span_names() == (
        SpanName.EXTRACTION_PRIMARY_OCR.value,
        SpanName.EXTRACTION.value,
        SpanName.INGESTION_JOB.value,
    )
    assert {span.trace_id for span in spans} == {job.trace_id}
    assert job.parent_span_id is None
    assert extraction.parent_span_id == job.span_id
    assert ocr.parent_span_id == extraction.span_id


async def test_a_failing_stage_is_marked_and_reports_its_stage(
    observability: ObservabilityHarness,
) -> None:
    with ingestion_job_context(job_type="ingestion.process"):
        with pytest.raises(ValueError):
            async with traced_stage(SpanName.EXTRACTION, stage=JobStage.EXTRACTION):
                raise ValueError("extractor exploded")

        assert failed_stage() is JobStage.EXTRACTION

    assert observability.tracer.find(SpanName.EXTRACTION)[0].status is SpanStatus.ERROR


async def test_the_innermost_failing_stage_wins(observability: ObservabilityHarness) -> None:
    _ = observability
    with ingestion_job_context(job_type="ingestion.process"):
        with pytest.raises(ValueError):
            async with traced_stage(SpanName.ARTIFACT_LOAD, stage=JobStage.ARTIFACT_LOAD):
                async with traced_stage(
                    SpanName.ARTIFACT_INTEGRITY,
                    stage=JobStage.ARTIFACT_INTEGRITY,
                ):
                    raise ValueError("hash mismatch")

        assert failed_stage() is JobStage.ARTIFACT_INTEGRITY


async def test_duration_is_recorded_with_the_stage_outcome(
    observability: ObservabilityHarness,
) -> None:
    with ingestion_job_context(job_type="ingestion.process", language_code="ar"):
        async with traced_stage(
            SpanName.EXTRACTION,
            duration_metric=MetricName.EXTRACTION_DURATION_SECONDS,
            labels={LabelKey.EXTRACTOR_METHOD: "openai_ocr"},
        ):
            pass

    labels = {
        LabelKey.EXTRACTOR_METHOD: "openai_ocr",
        LabelKey.STATUS: "success",
        LabelKey.LANGUAGE: "ar",
    }
    assert (
        observability.metrics.histogram_count(
            MetricName.EXTRACTION_DURATION_SECONDS,
            labels=labels,
        )
        == 1
    )


async def test_language_updates_inside_a_job_reach_later_metrics(
    observability: ObservabilityHarness,
) -> None:
    with ingestion_job_context(job_type="ingestion.process"):
        update_job_context(language_code="ar")
        async with traced_stage(
            SpanName.PERSISTENCE,
            duration_metric=MetricName.PERSISTENCE_DURATION_SECONDS,
        ):
            pass

    assert (
        observability.metrics.histogram_count(
            MetricName.PERSISTENCE_DURATION_SECONDS,
            labels={LabelKey.STATUS: "success", LabelKey.LANGUAGE: "ar"},
        )
        == 1
    )


async def test_a_broken_tracer_does_not_break_the_business_operation() -> None:
    previous = NullTracer()
    set_tracer(ExplodingTracer())  # type: ignore[arg-type]
    try:
        async with traced_stage(SpanName.EXTRACTION) as observation:
            outcome = "extraction completed"

        assert outcome == "extraction completed"
        assert observation.span is None
    finally:
        set_tracer(previous)


async def test_a_broken_metrics_backend_does_not_break_the_business_operation() -> None:
    set_metrics(ExplodingMetrics())  # type: ignore[arg-type]
    try:
        async with traced_stage(
            SpanName.EXTRACTION,
            duration_metric=MetricName.EXTRACTION_DURATION_SECONDS,
        ):
            outcome = "extraction completed"

        record_job_started(job_type="ingestion.process")

        assert outcome == "extraction completed"
    finally:
        set_metrics(NullMetricsRecorder())


async def test_a_broken_backend_still_lets_business_errors_propagate() -> None:
    set_tracer(ExplodingTracer())  # type: ignore[arg-type]
    set_metrics(ExplodingMetrics())  # type: ignore[arg-type]
    try:
        with pytest.raises(ValueError, match="extractor exploded"):
            async with traced_stage(SpanName.EXTRACTION, stage=JobStage.EXTRACTION):
                raise ValueError("extractor exploded")
    finally:
        set_tracer(InMemoryTracer())
        set_metrics(NullMetricsRecorder())


def test_the_null_tracer_yields_an_inert_span() -> None:
    set_tracer(NullTracer())
    set_metrics(NullMetricsRecorder())

    with traced_stage_sync(SpanName.CHUNKING) as observation:
        observation.set_attribute("chunk_count", 3)

    span = observation.span
    assert span is not None
    assert span.trace_id == ""
