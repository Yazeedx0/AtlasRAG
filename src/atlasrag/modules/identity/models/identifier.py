import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    text,
    CheckConstraint,
    Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from atlasrag.platform.database.base import Base


class UserIdentifier(Base):

    __tablename__ = "user_identifier"
    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="valid_to_after_valid_from",
        ),
        Index(
            "ix_user_identifiers_user_principal_id",
            "user_principal_id",
        ),
        Index(
            "uq_user_identifiers_active_identity",
            "identifier_type",
            "issuer",
            "normalized_value",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        {"schema": "iam"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam.users.principal_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    identifier_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    identifier_value: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    normalized_value: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    issuer: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="local",
        server_default=text("local"),
    )

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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