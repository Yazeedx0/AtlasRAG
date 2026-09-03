import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class IngestionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ClaimedIngestionItem:
    ingestion_item_id: uuid.UUID
    document_artifact_id: uuid.UUID
    attempt_number: int
    claimed_at: datetime
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionRunState:
    id: uuid.UUID
    configuration: dict[str, object]
    configuration_hash: str
    created_by_principal_id: uuid.UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionItemState:
    id: uuid.UUID
    ingestion_run_id: uuid.UUID
    document_artifact_id: uuid.UUID
    status: IngestionStatus
    attempt_count: int
    claimed_at: datetime | None
    lease_expires_at: datetime | None
    observed_file_hash: str | None
    execution_metadata: dict[str, object]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    activated_at: datetime | None
    deactivated_at: datetime | None
    created_at: datetime


__all__ = [
    "ClaimedIngestionItem",
    "IngestionItemState",
    "IngestionRunState",
    "IngestionStatus",
]
