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
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.contracts.types.embedding import EmbeddingStatus
from atlasrag.platform.database.base import Base

EMBEDDING_STATUS_DB_ENUM = SqlEnum(
    EmbeddingStatus,
    name="embedding_status",
    schema="knowledge",
    values_callable=lambda enum: [member.value for member in enum],
)


class EmbeddingRun(Base):
    __tablename__ = "embedding_runs"

    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
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
        Index(
            "uq_embedding_runs_in_flight",
            "ingestion_item_id",
            "embedding_model_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        Index("ix_embedding_runs_ingestion_item_id", "ingestion_item_id"),
        Index("ix_embedding_runs_embedding_model_id", "embedding_model_id"),
        Index("ix_embedding_runs_status", "status"),
        Index(
            "ix_embedding_runs_expired_running_lease",
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

    ingestion_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.ingestion_items.id", ondelete="RESTRICT"),
        nullable=False,
    )

    embedding_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.embedding_models.id", ondelete="RESTRICT"),
        nullable=False,
    )

    configuration: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[EmbeddingStatus] = mapped_column(
        EMBEDDING_STATUS_DB_ENUM,
        nullable=False,
        server_default=text("'pending'"),
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    error_code: Mapped[str | None] = mapped_column(String(150), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    execution_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    created_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("iam.principals.id", ondelete="SET NULL"),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = ["EMBEDDING_STATUS_DB_ENUM", "EmbeddingRun"]
