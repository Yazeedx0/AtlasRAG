import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.platform.database.base import Base


class JobOutbox(Base):
    __tablename__ = "job_outbox"

    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        CheckConstraint(
            "lease_expires_at IS NULL OR (claimed_at IS NOT NULL "
            "AND lease_expires_at > claimed_at)",
            name="valid_publish_lease",
        ),
        CheckConstraint(
            "published_at IS NULL OR lease_expires_at IS NULL",
            name="published_job_has_no_lease",
        ),
        CheckConstraint(
            "failed_at IS NULL OR lease_expires_at IS NULL",
            name="failed_job_has_no_lease",
        ),
        CheckConstraint(
            "NOT (published_at IS NOT NULL AND failed_at IS NOT NULL)",
            name="published_or_failed",
        ),
        CheckConstraint(
            "(failed_at IS NULL AND failure_code IS NULL) OR "
            "(failed_at IS NOT NULL AND failure_code IS NOT NULL "
            "AND length(btrim(failure_code)) > 0)",
            name="terminal_failure_complete",
        ),
        Index(
            "ix_job_outbox_unpublished_created_at",
            "created_at",
            postgresql_where=text("published_at IS NULL AND failed_at IS NULL"),
        ),
        Index(
            "ix_job_outbox_unpublished_lease_expires_at",
            "lease_expires_at",
            postgresql_where=text("published_at IS NULL AND failed_at IS NULL"),
        ),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
