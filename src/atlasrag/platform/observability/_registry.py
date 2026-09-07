import structlog

from atlasrag.contracts.observability import MetricsRecorder, Tracer
from atlasrag.platform.observability._logging import configure_structured_logging
from atlasrag.platform.observability._metrics import InMemoryMetricsRecorder, NullMetricsRecorder
from atlasrag.platform.observability._tracing import NullTracer, StructlogTracer

_logger = structlog.get_logger(__name__)

_tracer: Tracer = NullTracer()
_metrics: MetricsRecorder = NullMetricsRecorder()


def get_tracer() -> Tracer:
    return _tracer


def get_metrics() -> MetricsRecorder:
    return _metrics


def set_tracer(tracer: Tracer) -> None:
    global _tracer
    _tracer = tracer


def set_metrics(metrics: MetricsRecorder) -> None:
    global _metrics
    _metrics = metrics


def reset_observability() -> None:
    set_tracer(NullTracer())
    set_metrics(NullMetricsRecorder())


def configure_observability(
    *,
    log_level: str = "INFO",
    json_logs: bool = True,
    tracing_enabled: bool = True,
    metrics_enabled: bool = True,
) -> None:
    configure_structured_logging(level=log_level, json_output=json_logs)
    set_tracer(StructlogTracer() if tracing_enabled else NullTracer())
    set_metrics(InMemoryMetricsRecorder() if metrics_enabled else NullMetricsRecorder())
    _logger.info(
        "observability_configured",
        log_level=log_level,
        json_logs=json_logs,
        tracing_enabled=tracing_enabled,
        metrics_enabled=metrics_enabled,
    )


__all__ = [
    "configure_observability",
    "get_metrics",
    "get_tracer",
    "reset_observability",
    "set_metrics",
    "set_tracer",
]
