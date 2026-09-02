import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.contracts.types import IngestionStatus
from atlasrag.platform.database.base import Base

INGESTION_STATUS_DB_ENUM = SqlEnum(
    IngestionStatus,
    name="ingestion_status",
    schema="knowledge",
    values_callable=lambda enum: [member.value for member in enum],
)


class IngestionItem(Base):
    __tablename__ = "ingestion_items"

    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0",
            name="attempt_count_non_negative",
        ),
        CheckConstraint(
            """
            status != 'running'
            OR (
                started_at IS NOT NULL
                AND claimed_at IS NOT NULL
                AND lease_expires_at IS NOT NULL
            )
            """,
            name="running_requires_claim",
        ),
        CheckConstraint(
            """
            status = 'running'
            OR lease_expires_at IS NULL
            """,
            name="lease_only_while_running",
        ),
        CheckConstraint(
            """
            lease_expires_at IS NULL
            OR (
                claimed_at IS NOT NULL
                AND lease_expires_at > claimed_at
            )
            """,
            name="valid_lease",
        ),
        CheckConstraint(
            """
            status NOT IN ('completed', 'failed')
            OR completed_at IS NOT NULL
            """,
            name="terminal_requires_completed_at",
        ),
        CheckConstraint(
            """
            completed_at IS NULL
            OR (
                started_at IS NOT NULL
                AND completed_at >= started_at
            )
            """,
            name="completed_not_before_started",
        ),
        CheckConstraint(
            """
            activated_at IS NULL
            OR status = 'completed'
            """,
            name="activation_requires_completion",
        ),
        CheckConstraint(
            """
            deactivated_at IS NULL
            OR (
                activated_at IS NOT NULL
                AND deactivated_at >= activated_at
            )
            """,
            name="deactivation_after_activation",
        ),
        UniqueConstraint(
            "ingestion_run_id",
            "document_artifact_id",
            name="uq_ingestion_items_run_artifact",
        ),
        Index(
            "uq_ingestion_items_active_artifact",
            "document_artifact_id",
            unique=True,
            postgresql_where=text(
                "activated_at IS NOT NULL "
                "AND deactivated_at IS NULL"
            ),
        ),
        Index(
            "ix_ingestion_items_document_artifact_id",
            "document_artifact_id",
        ),
        Index(
            "ix_ingestion_items_status",
            "status",
        ),
        Index(
            "ix_ingestion_items_expired_running_lease",
            "lease_expires_at",
            postgresql_where=text("status = 'running'"),
        ),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge.ingestion_runs.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    document_artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge.document_artifacts.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    status: Mapped[IngestionStatus] = mapped_column(
        INGESTION_STATUS_DB_ENUM,
        nullable=False,
        server_default=text("'pending'"),
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    observed_file_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    execution_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    error_code: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )