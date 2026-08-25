"""remove password hash and default identifier validity start

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "password_hash", schema="iam")
    op.alter_column(
        "user_identifier",
        "valid_from",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        existing_nullable=True,
        schema="iam",
    )


def downgrade() -> None:
    op.alter_column(
        "user_identifier",
        "valid_from",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
        existing_nullable=True,
        schema="iam",
    )
    op.add_column(
        "users",
        sa.Column("password_hash", sa.Text(), nullable=True),
        schema="iam",
    )
