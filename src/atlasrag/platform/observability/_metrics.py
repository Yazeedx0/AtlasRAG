import threading
from collections.abc import Mapping

from atlasrag.contracts.types.observability import (
    LabelKey,
    MetricKind,
    MetricName,
    MetricSample,
)
from atlasrag.platform.observability._cardinality import (
    MAX_SERIES_PER_METRIC,
    METRIC_DEFINITIONS,
    MetricCardinalityError,
    validate_labels,
)

_SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


def _series_key(name: MetricName, labels: Mapping[str, str]) -> _SeriesKey:
    return (name.value, tuple(sorted(labels.items())))


class NullMetricsRecorder:
    def increment(
        self,
        name: MetricName,
        *,
        labels: Mapping[LabelKey, str] | None = None,
        value: float = 1.0,
    ) -> None:
        return None

    def observe(
        self,
        name: MetricName,
        value: float,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> None:
        return None

    def set_gauge(
        self,
        name: MetricName,
        value: float,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> None:
        return None


class InMemoryMetricsRecorder:
    def __init__(self, *, max_series_per_metric: int = MAX_SERIES_PER_METRIC) -> None:
        self._lock = threading.Lock()
        self._max_series_per_metric = max_series_per_metric
        self._counters: dict[_SeriesKey, float] = {}
        self._gauges: dict[_SeriesKey, float] = {}
        self._histogram_sums: dict[_SeriesKey, float] = {}
        self._histogram_counts: dict[_SeriesKey, int] = {}
        self._series_by_metric: dict[str, set[_SeriesKey]] = {}
        self._dropped_series: dict[str, int] = {}

    def increment(
        self,
        name: MetricName,
        *,
        labels: Mapping[LabelKey, str] | None = None,
        value: float = 1.0,
    ) -> None:
        key = self._prepare(name, labels, MetricKind.COUNTER)
        if key is None:
            return None
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value
        return None

    def observe(
        self,
        name: MetricName,
        value: float,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> None:
        key = self._prepare(name, labels, MetricKind.HISTOGRAM)
        if key is None:
            return None
        with self._lock:
            self._histogram_sums[key] = self._histogram_sums.get(key, 0.0) + value
            self._histogram_counts[key] = self._histogram_counts.get(key, 0) + 1
        return None

    def set_gauge(
        self,
        name: MetricName,
        value: float,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> None:
        key = self._prepare(name, labels, MetricKind.GAUGE)
        if key is None:
            return None
        with self._lock:
            self._gauges[key] = value
        return None

    def snapshot(self) -> tuple[MetricSample, ...]:
        with self._lock:
            counters = [
                MetricSample(
                    name=key[0],
                    kind=MetricKind.COUNTER,
                    labels=dict(key[1]),
                    value=value,
                    count=1,
                )
                for key, value in self._counters.items()
            ]
            gauges = [
                MetricSample(
                    name=key[0],
                    kind=MetricKind.GAUGE,
                    labels=dict(key[1]),
                    value=value,
                    count=1,
                )
                for key, value in self._gauges.items()
            ]
            histograms = [
                MetricSample(
                    name=key[0],
                    kind=MetricKind.HISTOGRAM,
                    labels=dict(key[1]),
                    value=value,
                    count=self._histogram_counts.get(key, 0),
                )
                for key, value in self._histogram_sums.items()
            ]
        return tuple(counters + gauges + histograms)

    def counter_value(
        self,
        name: MetricName,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> float:
        key = _series_key(name, validate_labels(name, labels))
        with self._lock:
            return self._counters.get(key, 0.0)

    def gauge_value(
        self,
        name: MetricName,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> float | None:
        key = _series_key(name, validate_labels(name, labels))
        with self._lock:
            return self._gauges.get(key)

    def histogram_count(
        self,
        name: MetricName,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> int:
        key = _series_key(name, validate_labels(name, labels))
        with self._lock:
            return self._histogram_counts.get(key, 0)

    def histogram_sum(
        self,
        name: MetricName,
        *,
        labels: Mapping[LabelKey, str] | None = None,
    ) -> float:
        key = _series_key(name, validate_labels(name, labels))
        with self._lock:
            return self._histogram_sums.get(key, 0.0)

    def label_keys(self, name: MetricName) -> frozenset[str]:
        with self._lock:
            series = self._series_by_metric.get(name.value, set())
            return frozenset(label for key in series for label, _ in key[1])

    def dropped_series(self, name: MetricName) -> int:
        with self._lock:
            return self._dropped_series.get(name.value, 0)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histogram_sums.clear()
            self._histogram_counts.clear()
            self._series_by_metric.clear()
            self._dropped_series.clear()

    def _prepare(
        self,
        name: MetricName,
        labels: Mapping[LabelKey, str] | None,
        kind: MetricKind,
    ) -> _SeriesKey | None:
        definition = METRIC_DEFINITIONS.get(name)
        if definition is None:
            raise MetricCardinalityError(f"Metric {name.value!r} has no cardinality definition.")
        if definition.kind is not kind:
            raise MetricCardinalityError(
                f"Metric {name.value!r} is a {definition.kind.value}, not a {kind.value}."
            )

        key = _series_key(name, validate_labels(name, labels))
        with self._lock:
            series = self._series_by_metric.setdefault(name.value, set())
            if key not in series:
                if len(series) >= self._max_series_per_metric:
                    self._dropped_series[name.value] = self._dropped_series.get(name.value, 0) + 1
                    return None
                series.add(key)
        return key


__all__ = ["InMemoryMetricsRecorder", "NullMetricsRecorder"]
