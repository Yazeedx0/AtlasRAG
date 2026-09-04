import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.modules.identity.enums import PRINCIPAL_TYPE_DB_ENUM, PrincipalType
from atlasrag.platform.database import Base


class Principal(Base):
    __tablename__ = "principals"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "type",
            name="id_type",
        ),
        CheckConstraint(
            "deleted_at IS NULL OR is_active = false",
            name="deleted_principal_inactive",
        ),
        CheckConstraint(
            "status_changed_at >= created_at",
            name="status_changed_not_before_created",
        ),
        {"schema": "iam"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    type: Mapped[PrincipalType] = mapped_column(
        PRINCIPAL_TYPE_DB_ENUM,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )

    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
