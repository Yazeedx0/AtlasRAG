import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.contracts.types.authorization_types import DocumentVersionStatus
from atlasrag.platform.database.base import Base

DOCUMENT_VERSION_STATUS_DB_ENUM = SqlEnum(
    DocumentVersionStatus,
    name="document_version_status",
    schema="knowledge",
    values_callable=lambda enum: [member.value for member in enum],
)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_label",
            name="uq_document_versions_document_id_version_label",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="effective_to_after_from",
        ),
        CheckConstraint(
            "status != 'published' OR (published_at IS NOT NULL AND effective_from IS NOT NULL)",
            name="published_requires_dates",
        ),
        CheckConstraint(
            "status NOT IN ('withdrawn', 'archived') "
            "OR (published_at IS NOT NULL "
            "AND effective_from IS NOT NULL "
            "AND effective_to IS NOT NULL)",
            name="closed_requires_dates",
        ),
        ExcludeConstraint(
            ("document_id", "="),
            ("effective_period", "&&"),
            name="ex_document_versions_no_overlapping_effective_period",
            where=text("effective_period IS NOT NULL"),
            deferrable=True,
            initially="IMMEDIATE",
        ),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    version_label: Mapped[str] = mapped_column(String(100), nullable=False)

    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_period: Mapped[object | None] = mapped_column(
        TSTZRANGE,
        Computed(
            "CASE WHEN effective_from IS NULL THEN NULL "
            "ELSE tstzrange(effective_from, effective_to, '[)') END",
            persisted=True,
        ),
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[DocumentVersionStatus] = mapped_column(
        DOCUMENT_VERSION_STATUS_DB_ENUM,
        nullable=False,
        default=DocumentVersionStatus.DRAFT,
    )

    created_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("iam.principals.id", ondelete="SET NULL"),
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
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )
