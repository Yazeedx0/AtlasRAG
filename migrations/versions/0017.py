"""add document descriptive fields

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("description", sa.Text(), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("document_type", sa.String(length=100), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("department", sa.String(length=100), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("default_language_code", sa.String(length=20), nullable=True),
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_column("documents", "default_language_code", schema="knowledge")
    op.drop_column("documents", "department", schema="knowledge")
    op.drop_column("documents", "document_type", schema="knowledge")
    op.drop_column("documents", "description", schema="knowledge")
