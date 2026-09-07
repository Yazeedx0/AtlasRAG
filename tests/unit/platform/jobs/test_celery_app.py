from datetime import timedelta

from celery import Celery

from atlasrag.platform.jobs.celery_app import create_celery_app
from atlasrag.platform.jobs.constants import (
    EMBEDDING_QUEUE,
    INGESTION_QUEUE,
    MAINTENANCE_QUEUE,
    PROCESS_EMBEDDING_TASK,
    PROCESS_INGESTION_TASK,
    PUBLISH_OUTBOX_SCHEDULE,
    PUBLISH_OUTBOX_TASK,
    RECOVER_INGESTION_LEASES_SCHEDULE,
    RECOVER_INGESTION_LEASES_TASK,
)


def make_app(**overrides: object) -> Celery:
    arguments: dict[str, object] = {
        "broker_url": "redis://localhost:6379/0",
        "database_url": "postgresql+asyncpg://atlas:atlas@localhost:5432/atlasrag",
        "database_echo": False,
        "outbox_publish_batch_size": 100,
        "outbox_publish_lease_seconds": 60,
    }
    arguments.update(overrides)
    return create_celery_app(**arguments)


def test_celery_app_routes_stable_tasks_to_their_configured_queues() -> None:
    app = make_app()

    assert app.conf.task_ignore_result is True
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_routes == {
        PROCESS_INGESTION_TASK: {"queue": INGESTION_QUEUE},
        PROCESS_EMBEDDING_TASK: {"queue": EMBEDDING_QUEUE},
        PUBLISH_OUTBOX_TASK: {"queue": MAINTENANCE_QUEUE},
        RECOVER_INGESTION_LEASES_TASK: {"queue": MAINTENANCE_QUEUE},
        "atlasrag.maintenance.*": {"queue": MAINTENANCE_QUEUE},
    }


def test_celery_app_schedules_both_maintenance_sweeps_on_the_maintenance_queue() -> None:
    app = make_app(
        outbox_publish_interval_seconds=7,
        ingestion_lease_recovery_interval_seconds=90,
    )

    schedule = app.conf.beat_schedule

    assert schedule[PUBLISH_OUTBOX_SCHEDULE]["task"] == PUBLISH_OUTBOX_TASK
    assert schedule[PUBLISH_OUTBOX_SCHEDULE]["schedule"] == timedelta(seconds=7)
    assert schedule[PUBLISH_OUTBOX_SCHEDULE]["options"]["queue"] == MAINTENANCE_QUEUE
    assert schedule[RECOVER_INGESTION_LEASES_SCHEDULE]["task"] == (
        RECOVER_INGESTION_LEASES_TASK
    )
    assert schedule[RECOVER_INGESTION_LEASES_SCHEDULE]["schedule"] == timedelta(seconds=90)
    assert schedule[RECOVER_INGESTION_LEASES_SCHEDULE]["options"]["queue"] == (
        MAINTENANCE_QUEUE
    )


def test_scheduled_maintenance_beats_expire_before_the_next_tick() -> None:
    app = make_app(
        outbox_publish_interval_seconds=7,
        ingestion_lease_recovery_interval_seconds=90,
    )

    schedule = app.conf.beat_schedule

    assert schedule[PUBLISH_OUTBOX_SCHEDULE]["options"]["expires"] == 7
    assert schedule[RECOVER_INGESTION_LEASES_SCHEDULE]["options"]["expires"] == 90


def test_celery_app_runs_on_utc() -> None:
    app = make_app()

    assert app.conf.timezone == "UTC"
    assert app.conf.enable_utc is True


def test_worker_operations_settings_are_exposed_to_tasks() -> None:
    app = make_app(
        outbox_publish_max_attempts=7,
        outbox_publish_backoff_seconds=3,
        outbox_publish_backoff_max_seconds=120,
        ingestion_lease_recovery_batch_size=25,
        worker_shutdown_grace_seconds=45,
    )

    assert app.conf.atlas_outbox_publish_max_attempts == 7
    assert app.conf.atlas_outbox_publish_backoff_seconds == 3
    assert app.conf.atlas_outbox_publish_backoff_max_seconds == 120
    assert app.conf.atlas_ingestion_lease_recovery_batch_size == 25
    assert app.conf.atlas_worker_shutdown_grace_seconds == 45
