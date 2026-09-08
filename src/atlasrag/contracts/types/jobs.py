import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class JobType(StrEnum):
    PROCESS_INGESTION_ITEM = "ingestion.process"
    PROCESS_EMBEDDING = "embedding.process"


@dataclass(frozen=True, slots=True)
class ClaimedOutboxJob:
    id: uuid.UUID
    job_type: str
    aggregate_id: uuid.UUID
    payload: dict[str, object]
    attempt_number: int
    lease_expires_at: datetime


__all__ = ["ClaimedOutboxJob", "JobType"]
