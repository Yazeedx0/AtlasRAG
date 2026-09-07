import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

import structlog

from atlasrag.contracts.observability import SpanAttributeValue
from atlasrag.contracts.types.observability import (
    LabelKey,
    RecordedSpan,
    SpanName,
    SpanStatus,
)
from atlasrag.platform.observability._redaction import is_content_key, is_sensitive_key, scrub_text

_CURRENT_TRACE: ContextVar[str | None] = ContextVar("atlasrag_trace_id", default=None)
_CURRENT_SPAN: ContextVar[str | None] = ContextVar("atlasrag_span_id", default=None)


class MutableSpan:
    def __init__(
        self,
        *,
        name: SpanName,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        attributes: Mapping[str, SpanAttributeValue] | None = None,
    ) -> None:
        self._name = name
        self._trace_id = trace_id
        self._span_id = span_id
        self._parent_span_id = parent_span_id
        self._status = SpanStatus.OK
        self._attributes: dict[str, SpanAttributeValue] = {}
        if attributes:
            for key, value in attributes.items():
                self.set_attribute(key, value)

    @property
    def name(self) -> SpanName:
        return self._name

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def span_id(self) -> str:
        return self._span_id

    @property
    def parent_span_id(self) -> str | None:
        return self._parent_span_id

    @property
    def status(self) -> SpanStatus:
        return self._status

    @property
    def attributes(self) -> Mapping[str, SpanAttributeValue]:
        return dict(self._attributes)

    @property
    def labels(self) -> dict[LabelKey, str]:
        collected: dict[LabelKey, str] = {}
        for key in LabelKey:
            value = self._attributes.get(key.value)
            if isinstance(value, str):
                collected[key] = value
        return collected

    def set_attribute(self, key: str, value: SpanAttributeValue) -> None:
        if is_sensitive_key(key) or is_content_key(key):
            return None
        self._attributes[key] = scrub_text(value) if isinstance(value, str) else value
        return None

    def set_label(self, key: LabelKey, value: str) -> None:
        self._attributes[key.value] = value
        return None

    def set_status(self, status: SpanStatus) -> None:
        self._status = status
        return None

    def record_error(self, *, error_code: str) -> None:
        self._status = SpanStatus.ERROR
        self._attributes[LabelKey.ERROR_CODE.value] = error_code
        return None


class NullTracer:
    @contextmanager
    def start_span(
        self,
        name: SpanName,
        *,
        attributes: Mapping[str, SpanAttributeValue] | None = None,
    ) -> Iterator[MutableSpan]:
        yield MutableSpan(
            name=name,
            trace_id="",
            span_id="",
            parent_span_id=None,
            attributes=attributes,
        )


class StructlogTracer:
    def __init__(self, *, logger_name: str = "atlasrag.trace") -> None:
        self._logger = structlog.get_logger(logger_name)

    @contextmanager
    def start_span(
        self,
        name: SpanName,
        *,
        attributes: Mapping[str, SpanAttributeValue] | None = None,
    ) -> Iterator[MutableSpan]:
        parent_span_id = _CURRENT_SPAN.get()
        trace_id = _CURRENT_TRACE.get() or uuid.uuid4().hex
        span = MutableSpan(
            name=name,
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=parent_span_id,
            attributes=attributes,
        )
        trace_token = _CURRENT_TRACE.set(trace_id)
        span_token = _CURRENT_SPAN.set(span.span_id)
        started = time.perf_counter()
        try:
            yield span
        except BaseException:
            span.set_status(SpanStatus.ERROR)
            raise
        finally:
            _CURRENT_SPAN.reset(span_token)
            _CURRENT_TRACE.reset(trace_token)
            self._emit(span=span, duration_seconds=time.perf_counter() - started)

    def _emit(self, *, span: MutableSpan, duration_seconds: float) -> None:
        self._logger.info(
            "span.end",
            span_name=span.name.value,
            trace_id=span.trace_id,
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            span_status=span.status.value,
            duration_ms=round(duration_seconds * 1000, 3),
            **span.attributes,
        )


class InMemoryTracer:
    def __init__(self) -> None:
        self._spans: list[RecordedSpan] = []

    @property
    def spans(self) -> tuple[RecordedSpan, ...]:
        return tuple(self._spans)

    def span_names(self) -> tuple[str, ...]:
        return tuple(span.name for span in self._spans)

    def find(self, name: SpanName) -> tuple[RecordedSpan, ...]:
        return tuple(span for span in self._spans if span.name == name.value)

    def reset(self) -> None:
        self._spans.clear()

    @contextmanager
    def start_span(
        self,
        name: SpanName,
        *,
        attributes: Mapping[str, SpanAttributeValue] | None = None,
    ) -> Iterator[MutableSpan]:
        parent_span_id = _CURRENT_SPAN.get()
        trace_id = _CURRENT_TRACE.get() or uuid.uuid4().hex
        span = MutableSpan(
            name=name,
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=parent_span_id,
            attributes=attributes,
        )
        trace_token = _CURRENT_TRACE.set(trace_id)
        span_token = _CURRENT_SPAN.set(span.span_id)
        started = time.perf_counter()
        try:
            yield span
        except BaseException:
            span.set_status(SpanStatus.ERROR)
            raise
        finally:
            _CURRENT_SPAN.reset(span_token)
            _CURRENT_TRACE.reset(trace_token)
            self._spans.append(
                RecordedSpan(
                    name=span.name.value,
                    trace_id=span.trace_id,
                    span_id=span.span_id,
                    parent_span_id=span.parent_span_id,
                    status=span.status,
                    duration_seconds=time.perf_counter() - started,
                    attributes=span.attributes,
                )
            )


__all__ = ["InMemoryTracer", "MutableSpan", "NullTracer", "StructlogTracer"]
