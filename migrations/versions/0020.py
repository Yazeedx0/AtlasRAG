"""add document artifacts table

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_ARTIFACT_STATUS_VALUES = ("available", "missing", "retired", "deleted")


def upgrade() -> None:
    document_artifact_status = postgresql.ENUM(
        *DOCUMENT_ARTIFACT_STATUS_VALUES,
        name="document_artifact_status",
        schema="knowledge",
    )
    document_artifact_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "document_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("artifact_key", sa.String(length=255), nullable=False),
        sa.Column("language_code", sa.String(length=20), nullable=False),
        sa.Column("source_name", sa.String(length=500), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storage_provider", sa.String(length=50), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=150), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *DOCUMENT_ARTIFACT_STATUS_VALUES,
                name="document_artifact_status",
                schema="knowledge",
                create_type=False,
            ),
            nullable=False,
            server_default="available",
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
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "file_size_bytes >= 0",
            name=op.f("ck_document_artifacts_document_artifact_file_size_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["knowledge.document_versions.id"],
            name=op.f("fk_document_artifacts_document_version_id_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_document_artifacts_created_by_principal_id_principals"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_artifacts")),
        sa.UniqueConstraint(
            "document_version_id",
            "artifact_key",
            name=op.f("uq_document_artifacts_version_artifact_key"),
        ),
        sa.UniqueConstraint(
            "storage_provider",
            "storage_key",
            name=op.f("uq_document_artifacts_storage_location"),
        ),
        schema="knowledge",
    )

    op.create_index(
        op.f("ix_document_artifacts_document_version_id"),
        "document_artifacts",
        ["document_version_id"],
        unique=False,
        schema="knowledge",
    )
    op.create_index(
        op.f("ix_document_artifacts_file_hash"),
        "document_artifacts",
        ["file_hash"],
        unique=False,
        schema="knowledge",
    )
    op.create_index(
        op.f("ix_document_artifacts_status"),
        "document_artifacts",
        ["status"],
        unique=False,
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_table("document_artifacts", schema="knowledge")

    document_artifact_status = postgresql.ENUM(
        *DOCUMENT_ARTIFACT_STATUS_VALUES,
        name="document_artifact_status",
        schema="knowledge",
    )
    document_artifact_status.drop(op.get_bind(), checkfirst=True)
