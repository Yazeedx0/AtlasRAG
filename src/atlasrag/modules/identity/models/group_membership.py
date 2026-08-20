import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.modules.identity.enums import PRINCIPAL_TYPE_DB_ENUM, PrincipalType
from atlasrag.platform.database import Base


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["member_principal_id", "member_type"],
            ["iam.principals.id", "iam.principals.type"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "member_type IN ('user', 'group')",
            name="member_type_user_or_group",
        ),
        CheckConstraint(
            "group_principal_id != member_principal_id",
            name="no_self_membership",
        ),
        CheckConstraint(
            "removed_at IS NULL OR removed_at >= added_at",
            name="removed_not_before_added",
        ),
        Index(
            "ix_group_memberships_group_principal_id",
            "group_principal_id",
        ),
        Index(
            "ix_group_memberships_member_principal_id",
            "member_principal_id",
        ),
        Index(
            "ix_group_memberships_member_principal_type",
            "member_principal_id",
            "member_type",
        ),
        Index(
            "uq_group_memberships_active_membership",
            "group_principal_id",
            "member_principal_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        {"schema": "iam"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    group_principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam.groups.principal_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    member_principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    member_type: Mapped[PrincipalType] = mapped_column(
        PRINCIPAL_TYPE_DB_ENUM,
        nullable=False,
    )

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    added_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam.principals.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    removed_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam.principals.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )