"""add document versions table

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_VERSION_STATUS_VALUES = ("draft", "published", "withdrawn", "archived")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    document_version_status = postgresql.ENUM(
        *DOCUMENT_VERSION_STATUS_VALUES,
        name="document_version_status",
        schema="knowledge",
    )
    document_version_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version_label", sa.String(length=100), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "effective_period",
            postgresql.TSTZRANGE(),
            sa.Computed(
                "CASE WHEN effective_from IS NULL THEN NULL "
                "ELSE tstzrange(effective_from, effective_to, '[)') END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                *DOCUMENT_VERSION_STATUS_VALUES,
                name="document_version_status",
                schema="knowledge",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("created_by_principal_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name=op.f("ck_document_versions_effective_to_after_from"),
        ),
        sa.CheckConstraint(
            "status != 'published' OR (published_at IS NOT NULL AND effective_from IS NOT NULL)",
            name=op.f("ck_document_versions_published_requires_dates"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('withdrawn', 'archived') "
            "OR (published_at IS NOT NULL "
            "AND effective_from IS NOT NULL "
            "AND effective_to IS NOT NULL)",
            name=op.f("ck_document_versions_closed_requires_dates"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge.documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_document_versions_created_by_principal_id_principals"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "document_id",
            "version_label",
            name=op.f("uq_document_versions_document_id_version_label"),
        ),
        schema="knowledge",
    )

    op.execute(
        "ALTER TABLE knowledge.document_versions "
        "ADD CONSTRAINT ex_document_versions_no_overlapping_effective_period "
        "EXCLUDE USING gist (document_id WITH =, effective_period WITH &&) "
        "WHERE (effective_period IS NOT NULL) "
        "DEFERRABLE INITIALLY IMMEDIATE"
    )


def downgrade() -> None:
    op.drop_table("document_versions", schema="knowledge")

    document_version_status = postgresql.ENUM(
        *DOCUMENT_VERSION_STATUS_VALUES,
        name="document_version_status",
        schema="knowledge",
    )
    document_version_status.drop(op.get_bind(), checkfirst=True)
