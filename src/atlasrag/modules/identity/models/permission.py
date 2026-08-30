from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.platform.database.base import Base


class PermissionDefinition(Base):
    __tablename__ = "permissions"
    __table_args__ = {"schema": "iam"}

    permission_key: Mapped[str] = mapped_column(
        String(150),
        primary_key=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
