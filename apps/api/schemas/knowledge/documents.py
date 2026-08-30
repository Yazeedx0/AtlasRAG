from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atlasrag.contracts.types.authorization_types import DocumentPermission


class DocumentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_key: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    document_type: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    default_language_code: str | None = Field(default=None, max_length=20)
    metadata: dict[str, object] = Field(default_factory=dict)


class DocumentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    document_type: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    default_language_code: str | None = Field(default=None, max_length=20)
    metadata: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one mutable document field is required")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        if "metadata" in self.model_fields_set and self.metadata is None:
            raise ValueError("metadata cannot be null")
        return self


class DocumentResponse(BaseModel):
    id: UUID
    created_by_principal_id: UUID | None
    canonical_key: str
    title: str
    description: str | None
    document_type: str | None
    department: str | None
    default_language_code: str | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class DocumentAclGrantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: UUID
    permission: DocumentPermission
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expires_at must include a timezone offset")
        return value


class DocumentAclGrantResponse(BaseModel):
    grant_id: UUID
    principal_id: UUID
    permission: DocumentPermission
    granted_at: datetime
    granted_by_principal_id: UUID | None
    expires_at: datetime | None
    revoked_at: datetime | None
    revoked_by_principal_id: UUID | None
