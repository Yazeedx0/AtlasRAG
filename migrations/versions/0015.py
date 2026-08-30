"""add document creator and ACL history index

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("created_by_principal_id", sa.UUID(), nullable=True),
        schema="knowledge",
    )
    op.create_foreign_key(
        "fk_documents_created_by_principal_id_principals",
        "documents",
        "principals",
        ["created_by_principal_id"],
        ["id"],
        source_schema="knowledge",
        referent_schema="iam",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_document_acl_document_id_granted_at",
        "document_acl",
        ["document_id", "granted_at", "id"],
        unique=False,
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_acl_document_id_granted_at",
        table_name="document_acl",
        schema="knowledge",
    )
    op.drop_constraint(
        "fk_documents_created_by_principal_id_principals",
        "documents",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_column("documents", "created_by_principal_id", schema="knowledge")
