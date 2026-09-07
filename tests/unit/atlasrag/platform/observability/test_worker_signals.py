from collections.abc import Iterator

import pytest
from celery import Celery
from celery.signals import task_failure, task_postrun, task_prerun, task_retry
from kombu import Queue
from tests.unit.conftest import ObservabilityHarness

from atlasrag.contracts.types.observability import LabelKey, MetricName
from atlasrag.platform.observability import install_celery_observability

pytestmark = pytest.mark.unit

_TASK_NAME = "atlasrag.ingestion.process"
_QUEUE = "atlasrag.ingestion"


class FakeRequest:
    def __init__(self, routing_key: str) -> None:
        self.delivery_info = {"routing_key": routing_key}


class FakeTask:
    def __init__(self, *, name: str, routing_key: str) -> None:
        self.name = name
        self.request = FakeRequest(routing_key)


@pytest.fixture
def celery_observability(
    observability: ObservabilityHarness,
) -> Iterator[ObservabilityHarness]:
    app = Celery("atlasrag-test")
    app.conf.update(task_queues=(Queue(_QUEUE), Queue("atlasrag.maintenance")))

    @app.task(name=_TASK_NAME)
    def process_ingestion() -> None:
        return None

    install_celery_observability(app)
    try:
        yield observability
    finally:
        for signal in (task_prerun, task_postrun, task_failure, task_retry):
            signal.receivers = []
            signal.sender_receivers_cache.clear()


def test_a_successful_task_records_start_completion_and_duration(
    celery_observability: ObservabilityHarness,
) -> None:
    task = FakeTask(name=_TASK_NAME, routing_key=_QUEUE)
    labels = {LabelKey.TASK_NAME: _TASK_NAME, LabelKey.QUEUE: _QUEUE}

    task_prerun.send(sender=task, task_id="task-1", task=task)
    task_postrun.send(sender=task, task_id="task-1", task=task, state="SUCCESS")

    metrics = celery_observability.metrics
    assert metrics.counter_value(MetricName.WORKER_TASKS_STARTED_TOTAL, labels=labels) == 1
    assert metrics.counter_value(MetricName.WORKER_TASKS_COMPLETED_TOTAL, labels=labels) == 1
    assert (
        metrics.histogram_count(
            MetricName.WORKER_TASK_DURATION_SECONDS,
            labels={**labels, LabelKey.STATUS: "success"},
        )
        == 1
    )


def test_a_failing_task_is_counted_with_a_bounded_error_code(
    celery_observability: ObservabilityHarness,
) -> None:
    task = FakeTask(name=_TASK_NAME, routing_key=_QUEUE)

    task_prerun.send(sender=task, task_id="task-2", task=task)
    task_failure.send(
        sender=task,
        task_id="task-2",
        exception=ConnectionResetError("broker at 10.0.0.9 reset the connection"),
    )
    task_postrun.send(sender=task, task_id="task-2", task=task, state="FAILURE")

    metrics = celery_observability.metrics
    assert (
        metrics.counter_value(
            MetricName.WORKER_TASKS_FAILED_TOTAL,
            labels={
                LabelKey.TASK_NAME: _TASK_NAME,
                LabelKey.QUEUE: _QUEUE,
                LabelKey.ERROR_CODE: "other",
            },
        )
        == 1
    )
    label_values = {value for sample in metrics.snapshot() for value in sample.labels.values()}
    assert "10.0.0.9" not in "".join(label_values)


def test_a_task_retry_is_counted(celery_observability: ObservabilityHarness) -> None:
    task = FakeTask(name=_TASK_NAME, routing_key=_QUEUE)

    task_retry.send(sender=task, request=task.request, reason="transient")

    assert (
        celery_observability.metrics.counter_value(
            MetricName.WORKER_TASK_RETRIES_TOTAL,
            labels={LabelKey.TASK_NAME: _TASK_NAME, LabelKey.QUEUE: _QUEUE},
        )
        == 1
    )


def test_unregistered_task_names_and_queues_collapse_to_unknown(
    celery_observability: ObservabilityHarness,
) -> None:
    task = FakeTask(name="attacker.controlled.task.name", routing_key="attacker.queue")

    task_prerun.send(sender=task, task_id="task-3", task=task)

    assert (
        celery_observability.metrics.counter_value(
            MetricName.WORKER_TASKS_STARTED_TOTAL,
            labels={LabelKey.TASK_NAME: "unknown", LabelKey.QUEUE: "unknown"},
        )
        == 1
    )
