from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from atlasrag.platform.observability import (
    InMemoryMetricsRecorder,
    InMemoryTracer,
    get_metrics,
    get_tracer,
    set_metrics,
    set_tracer,
)


@dataclass(frozen=True, slots=True)
class ObservabilityHarness:
    tracer: InMemoryTracer
    metrics: InMemoryMetricsRecorder

    def span_names(self) -> tuple[str, ...]:
        return self.tracer.span_names()


@pytest.fixture
def observability() -> Iterator[ObservabilityHarness]:
    previous_tracer = get_tracer()
    previous_metrics = get_metrics()
    tracer = InMemoryTracer()
    metrics = InMemoryMetricsRecorder()
    set_tracer(tracer)
    set_metrics(metrics)
    try:
        yield ObservabilityHarness(tracer=tracer, metrics=metrics)
    finally:
        set_tracer(previous_tracer)
        set_metrics(previous_metrics)
