import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.contracts.authorization_types import DocumentPermission
from atlasrag.platform.database.base import Base

DOCUMENT_PERMISSION_DB_ENUM = SqlEnum(
    DocumentPermission,
    name="document_permission",
    schema="knowledge",
    values_callable=lambda enum: [member.value for member in enum],
)


class DocumentACL(Base):
    __tablename__ = "document_acl"
    __table_args__ = (
        CheckConstraint(
            "expires_at IS NULL OR expires_at > granted_at",
            name="expires_after_grant",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="revoked_not_before_grant",
        ),
        Index(
            "uq_document_acl_active_grant",
            "document_id",
            "principal_id",
            "permission",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_document_acl_active_read_lookup",
            "document_id",
            "principal_id",
            postgresql_where=text(
                "revoked_at IS NULL AND permission IN ('read', 'manage')"
            ),
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
        ForeignKey(
            "knowledge.documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam.principals.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    permission: Mapped[DocumentPermission] = mapped_column(
        DOCUMENT_PERMISSION_DB_ENUM,
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

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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
