"""narrow active document ACL read lookup index

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_document_acl_active_read_lookup",
        table_name="document_acl",
        schema="knowledge",
        postgresql_where=sa.text(
            "revoked_at IS NULL AND permission IN ('read', 'manage')"
        ),
    )
    op.create_index(
        "ix_document_acl_active_read_lookup",
        "document_acl",
        ["document_id", "principal_id"],
        unique=False,
        schema="knowledge",
        postgresql_where=sa.text("revoked_at IS NULL AND permission = 'read'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_acl_active_read_lookup",
        table_name="document_acl",
        schema="knowledge",
        postgresql_where=sa.text("revoked_at IS NULL AND permission = 'read'"),
    )
    op.create_index(
        "ix_document_acl_active_read_lookup",
        "document_acl",
        ["document_id", "principal_id"],
        unique=False,
        schema="knowledge",
        postgresql_where=sa.text(
            "revoked_at IS NULL AND permission IN ('read', 'manage')"
        ),
    )
