import time
from collections.abc import Sequence
from typing import Any

import structlog
from celery import Celery
from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_unknown,
)

from atlasrag.contracts.types.observability import LabelKey, MetricName, OutcomeLabel
from atlasrag.platform.observability._cardinality import categorize_exception
from atlasrag.platform.observability._instrumentation import increment, observe

_logger = structlog.get_logger("atlasrag.worker")

_KNOWN_TASK_NAMES: set[str] = set()
_KNOWN_QUEUES: set[str] = set()
_STARTED_AT: dict[str, float] = {}
_APP: Celery | None = None

_UNKNOWN = "unknown"
_MAX_TRACKED_TASKS = 1000


def _refresh_known_task_names() -> None:
    app = _APP
    if app is not None:
        _KNOWN_TASK_NAMES.update(app.tasks.keys())
    return None


def _task_label(task_name: object) -> str:
    name = str(task_name) if task_name is not None else _UNKNOWN
    if name in _KNOWN_TASK_NAMES:
        return name
    _refresh_known_task_names()
    return name if name in _KNOWN_TASK_NAMES else _UNKNOWN


def _queue_label(task: Any) -> str:
    delivery_info = getattr(getattr(task, "request", None), "delivery_info", None)
    if isinstance(delivery_info, dict):
        routing_key = delivery_info.get("routing_key")
        if isinstance(routing_key, str) and routing_key in _KNOWN_QUEUES:
            return routing_key
    return _UNKNOWN


def register_task_names(*task_names: str) -> None:
    _KNOWN_TASK_NAMES.update(task_names)
    return None


def register_queues(*queues: str) -> None:
    _KNOWN_QUEUES.update(queues)
    return None


def _on_task_prerun(
    task_id: object = None,
    task: Any = None,
    sender: Any = None,
    **_: object,
) -> None:
    name = _task_label(getattr(sender, "name", None) or getattr(task, "name", None))
    queue = _queue_label(task or sender)
    if task_id is not None:
        if len(_STARTED_AT) >= _MAX_TRACKED_TASKS:
            _STARTED_AT.clear()
        _STARTED_AT[str(task_id)] = time.perf_counter()
    increment(
        MetricName.WORKER_TASKS_STARTED_TOTAL,
        labels={LabelKey.TASK_NAME: name, LabelKey.QUEUE: queue},
    )
    _logger.info("worker_task_started", task_name=name, queue=queue)
    return None


def _on_task_postrun(
    task_id: object = None,
    task: Any = None,
    sender: Any = None,
    state: object = None,
    **_: object,
) -> None:
    name = _task_label(getattr(sender, "name", None) or getattr(task, "name", None))
    queue = _queue_label(task or sender)
    started = _STARTED_AT.pop(str(task_id), None) if task_id is not None else None
    succeeded = str(state) == "SUCCESS"
    status = OutcomeLabel.SUCCESS if succeeded else OutcomeLabel.FAILURE
    if started is not None:
        observe(
            MetricName.WORKER_TASK_DURATION_SECONDS,
            time.perf_counter() - started,
            labels={
                LabelKey.TASK_NAME: name,
                LabelKey.QUEUE: queue,
                LabelKey.STATUS: status.value,
            },
        )
    if succeeded:
        increment(
            MetricName.WORKER_TASKS_COMPLETED_TOTAL,
            labels={LabelKey.TASK_NAME: name, LabelKey.QUEUE: queue},
        )
    _logger.info("worker_task_finished", task_name=name, queue=queue, task_status=status.value)
    return None


def _on_task_failure(
    task_id: object = None,
    exception: BaseException | None = None,
    sender: Any = None,
    **_: object,
) -> None:
    name = _task_label(getattr(sender, "name", None))
    queue = _queue_label(sender)
    error_code = categorize_exception(exception).value if exception is not None else _UNKNOWN
    increment(
        MetricName.WORKER_TASKS_FAILED_TOTAL,
        labels={
            LabelKey.TASK_NAME: name,
            LabelKey.QUEUE: queue,
            LabelKey.ERROR_CODE: error_code,
        },
    )
    _logger.error("worker_task_failed", task_name=name, queue=queue, error_code=error_code)
    return None


def _on_task_retry(sender: Any = None, **_: object) -> None:
    name = _task_label(getattr(sender, "name", None))
    queue = _queue_label(sender)
    increment(
        MetricName.WORKER_TASK_RETRIES_TOTAL,
        labels={LabelKey.TASK_NAME: name, LabelKey.QUEUE: queue},
    )
    _logger.warning("worker_task_retried", task_name=name, queue=queue)
    return None


def _on_task_unknown(name: object = None, **_: object) -> None:
    _logger.error("worker_task_unknown", task_name=_task_label(name))
    return None


def install_celery_observability(
    app: Celery,
    *,
    task_names: Sequence[str] = (),
) -> None:
    global _APP
    _APP = app
    register_task_names(*task_names, *app.tasks.keys())
    task_queues = app.conf.task_queues or ()
    register_queues(*(str(queue.name) for queue in task_queues))
    task_prerun.connect(_on_task_prerun, weak=False)
    task_postrun.connect(_on_task_postrun, weak=False)
    task_failure.connect(_on_task_failure, weak=False)
    task_retry.connect(_on_task_retry, weak=False)
    task_unknown.connect(_on_task_unknown, weak=False)
    return None


__all__ = ["install_celery_observability", "register_queues", "register_task_names"]
