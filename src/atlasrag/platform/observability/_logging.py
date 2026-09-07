import logging
import sys
from collections.abc import Sequence
from typing import Any

import structlog
from structlog.typing import Processor

from atlasrag.platform.observability._redaction import redact_event

_LOG_LEVELS: dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def resolve_log_level(level: str) -> int:
    return _LOG_LEVELS.get(level.strip().upper(), logging.INFO)


def build_processors(*, json_output: bool) -> Sequence[Processor]:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_event,
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    return [*shared, renderer]


def configure_structured_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    numeric_level = resolve_log_level(level)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )
    structlog.configure(
        processors=list(build_processors(json_output=json_output)),
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)


__all__ = [
    "build_processors",
    "configure_structured_logging",
    "get_logger",
    "resolve_log_level",
]
