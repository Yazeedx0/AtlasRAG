from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atlasrag.contracts.types.authorization_types import DocumentVersionStatus


class DocumentVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_label: str = Field(min_length=1, max_length=100)
    metadata: dict[str, object] = Field(default_factory=dict)


class DocumentVersionPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: datetime

    @field_validator("effective_from")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("effective_from must include a timezone offset")
        return value


class DocumentVersionWithdrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_to: datetime

    @field_validator("effective_to")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("effective_to must include a timezone offset")
        return value


class DocumentVersionResponse(BaseModel):
    id: UUID
    document_id: UUID
    version_label: str
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None
    status: DocumentVersionStatus
    created_by_principal_id: UUID | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
