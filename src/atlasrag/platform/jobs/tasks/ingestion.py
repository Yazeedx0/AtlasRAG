import uuid

from celery import Task

from atlasrag.platform.jobs.celery_app import celery_app
from atlasrag.platform.jobs.constants import PROCESS_INGESTION_TASK


@celery_app.task(
    name=PROCESS_INGESTION_TASK,
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def process_ingestion_item(self: Task, ingestion_item_id: str) -> None:
    _ = self
    uuid.UUID(ingestion_item_id)
