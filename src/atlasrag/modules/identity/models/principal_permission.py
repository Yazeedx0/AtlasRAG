import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.platform.database.base import Base


class PrincipalPermission(Base):
    __tablename__ = "principal_permissions"
    __table_args__ = (
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="principal_permission_revoked_not_before_granted",
        ),
        Index(
            "uq_principal_permissions_active",
            "principal_id",
            "permission_key",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_principal_permissions_permission_key",
            "permission_key",
        ),
        {"schema": "iam"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam.principals.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    permission_key: Mapped[str] = mapped_column(
        String(150),
        ForeignKey(
            "iam.permissions.permission_key",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    granted_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam.principals.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    revoked_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam.principals.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
