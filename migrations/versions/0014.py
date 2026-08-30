"""add manage document permission enum value

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE knowledge.document_permission "
        "ADD VALUE IF NOT EXISTS 'manage'"
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_manage_grants = connection.scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM knowledge.document_acl "
            "WHERE permission::text = 'manage'"
            ")"
        )
    )
    if has_manage_grants:
        raise RuntimeError(
            "Cannot downgrade document permissions while manage grants exist."
        )

    op.drop_index(
        "uq_document_acl_active_grant",
        table_name="document_acl",
        schema="knowledge",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_index(
        "ix_document_acl_active_read_lookup",
        table_name="document_acl",
        schema="knowledge",
        postgresql_where=sa.text(
            "revoked_at IS NULL AND permission IN ('read', 'manage')"
        ),
    )
    op.execute(
        "ALTER TABLE knowledge.document_acl "
        "ALTER COLUMN permission TYPE text"
    )
    op.execute("DROP TYPE knowledge.document_permission")
    op.execute(
        "CREATE TYPE knowledge.document_permission AS ENUM ('read')"
    )
    op.execute(
        "ALTER TABLE knowledge.document_acl "
        "ALTER COLUMN permission TYPE knowledge.document_permission "
        "USING permission::text::knowledge.document_permission"
    )
    op.create_index(
        "ix_document_acl_active_read_lookup",
        "document_acl",
        ["document_id", "principal_id"],
        unique=False,
        schema="knowledge",
        postgresql_where=sa.text("revoked_at IS NULL AND permission = 'read'"),
    )
    op.create_index(
        "uq_document_acl_active_grant",
        "document_acl",
        ["document_id", "principal_id", "permission"],
        unique=True,
        schema="knowledge",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
