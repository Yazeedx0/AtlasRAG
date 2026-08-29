"""add documents and document ACL tables

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_PERMISSION_VALUES = ("read", "manage")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")

    document_permission = postgresql.ENUM(
        *DOCUMENT_PERMISSION_VALUES,
        name="document_permission",
        schema="knowledge",
    )
    document_permission.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("document_type", sa.String(length=100), nullable=True),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("default_language_code", sa.String(length=20), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("canonical_key", name=op.f("uq_documents_canonical_key")),
        schema="knowledge",
    )

    op.create_table(
        "document_acl",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column(
            "permission",
            postgresql.ENUM(
                *DOCUMENT_PERMISSION_VALUES,
                name="document_permission",
                schema="knowledge",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by_principal_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_principal_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > granted_at",
            name=op.f("ck_document_acl_expires_after_grant"),
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name=op.f("ck_document_acl_revoked_not_before_grant"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge.documents.id"],
            name=op.f("fk_document_acl_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_document_acl_principal_id_principals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_document_acl_granted_by_principal_id_principals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_document_acl_revoked_by_principal_id_principals"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_acl")),
        schema="knowledge",
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
    op.create_index(
        "uq_document_acl_active_grant",
        "document_acl",
        ["document_id", "principal_id", "permission"],
        unique=True,
        schema="knowledge",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
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
    op.drop_table("document_acl", schema="knowledge")
    op.drop_table("documents", schema="knowledge")

    document_permission = postgresql.ENUM(
        *DOCUMENT_PERMISSION_VALUES,
        name="document_permission",
        schema="knowledge",
    )
    document_permission.drop(op.get_bind(), checkfirst=True)
