from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from atlasrag.contracts.types.observability import (
    LabelKey,
    MetricName,
    SpanName,
    SpanStatus,
)

SpanAttributeValue = str | int | float | bool


@runtime_checkable
class Span(Protocol):
    @property
    def trace_id(self) -> str:
        ...

    @property
    def span_id(self) -> str:
        ...

    def set_attribute(self, key: str, value: SpanAttributeValue) -> None:
        ...

    def set_label(self, key: LabelKey, value: str) -> None:
        ...

    def set_status(self, status: SpanStatus) -> None:
        ...

    def record_error(self, *, error_code: str) -> None:
        ...


@runtime_checkable
class Tracer(Protocol):
    def start_span(
        self,
        name: SpanName,
        *,
        attributes: Mapping[str, SpanAttributeValue] | None = None,
    ) -> AbstractContextManager[Span]:
        ...


@runtime_checkable
class MetricsRecorder(Protocol):
    def increment(
        self,
        name: MetricName,
        *,
        labels: Mapping[LabelKey, str] | None = None,
        value: float = 1.0,
    ) -> None:
        ...

    def observe(
        self,
        name: MetricName,
        value: float,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> None:
        ...

    def set_gauge(
        self,
        name: MetricName,
        value: float,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> None:
        ...


__all__ = ["MetricsRecorder", "Span", "SpanAttributeValue", "Tracer"]
