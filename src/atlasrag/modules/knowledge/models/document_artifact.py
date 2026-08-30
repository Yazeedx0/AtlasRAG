import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.contracts.types.authorization_types import DocumentArtifactStatus
from atlasrag.platform.database.base import Base

DOCUMENT_ARTIFACT_STATUS_DB_ENUM = SqlEnum(
    DocumentArtifactStatus,
    name="document_artifact_status",
    schema="knowledge",
    values_callable=lambda enum: [member.value for member in enum],
)


class DocumentArtifact(Base):
    __tablename__ = "document_artifacts"
    __table_args__ = (
        CheckConstraint(
            "file_size_bytes >= 0",
            name="document_artifact_file_size_non_negative",
        ),
        UniqueConstraint(
            "document_version_id",
            "artifact_key",
            name="uq_document_artifacts_version_artifact_key",
        ),
        UniqueConstraint(
            "storage_provider",
            "storage_key",
            name="uq_document_artifacts_storage_location",
        ),
        Index(
            "ix_document_artifacts_document_version_id",
            "document_version_id",
        ),
        Index(
            "ix_document_artifacts_file_hash",
            "file_hash",
        ),
        Index(
            "ix_document_artifacts_status",
            "status",
        ),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge.document_versions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    artifact_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    language_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    source_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    source_uri: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    storage_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    storage_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    mime_type: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    file_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    file_size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    status: Mapped[DocumentArtifactStatus] = mapped_column(
        DOCUMENT_ARTIFACT_STATUS_DB_ENUM,
        nullable=False,
        default=DocumentArtifactStatus.AVAILABLE,
    )

    created_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam.principals.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
