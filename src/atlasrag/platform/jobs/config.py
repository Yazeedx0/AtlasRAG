from collections.abc import Mapping

from atlasrag.contracts.types.jobs import JobType
from atlasrag.platform.jobs.constants import (
    PROCESS_INGESTION_TASK,
    PUBLISH_OUTBOX_TASK,
)

INGESTION_PROCESS_TASK_NAME = PROCESS_INGESTION_TASK
PUBLISH_OUTBOX_TASK_NAME = PUBLISH_OUTBOX_TASK

TASK_BY_JOB_TYPE: Mapping[str, str] = {
    JobType.PROCESS_INGESTION_ITEM.value: INGESTION_PROCESS_TASK_NAME,
    "ingestion.process_item": INGESTION_PROCESS_TASK_NAME,
}

__all__ = [
    "INGESTION_PROCESS_TASK_NAME",
    "PUBLISH_OUTBOX_TASK_NAME",
    "TASK_BY_JOB_TYPE",
]
