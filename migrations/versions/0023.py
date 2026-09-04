"""store principal timestamps with timezone

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMP_COLUMNS = ("created_at", "status_changed_at", "deleted_at")


def upgrade() -> None:
    for column_name in _TIMESTAMP_COLUMNS:
        op.alter_column(
            "principals",
            column_name,
            schema="iam",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
            existing_nullable=column_name == "deleted_at",
        )


def downgrade() -> None:
    for column_name in _TIMESTAMP_COLUMNS:
        op.alter_column(
            "principals",
            column_name,
            schema="iam",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
            existing_nullable=column_name == "deleted_at",
        )
