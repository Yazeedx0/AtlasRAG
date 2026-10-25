"""add ingestion chunks

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=20), nullable=False),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column(
            "section_path",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("language_code", sa.String(length=35), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name=op.f("ck_chunks_chunk_index_non_negative"),
        ),
        sa.CheckConstraint(
            "length(btrim(content)) > 0",
            name=op.f("ck_chunks_content_non_empty"),
        ),
        sa.CheckConstraint(
            "content_type IN ('text', 'table', 'code', 'mixed')",
            name=op.f("ck_chunks_valid_content_type"),
        ),
        sa.CheckConstraint(
            "token_count >= 0",
            name=op.f("ck_chunks_token_count_non_negative"),
        ),
        sa.CheckConstraint(
            "page_start IS NULL OR page_start > 0",
            name=op.f("ck_chunks_page_start_positive"),
        ),
        sa.CheckConstraint(
            "page_end IS NULL OR page_end > 0",
            name=op.f("ck_chunks_page_end_positive"),
        ),
        sa.CheckConstraint(
            "page_start IS NULL OR page_end IS NULL OR page_end >= page_start",
            name=op.f("ck_chunks_valid_page_range"),
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_item_id"],
            ["knowledge.ingestion_items.id"],
            name=op.f("fk_chunks_ingestion_item_id_ingestion_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("ingestion_item_id", "chunk_index", name=op.f("uq_chunks_item_index")),
        schema="knowledge",
    )
    op.create_index(
        "ix_chunks_ingestion_item_id",
        "chunks",
        ["ingestion_item_id"],
        schema="knowledge",
    )
    op.create_index("ix_chunks_content_hash", "chunks", ["content_hash"], schema="knowledge")


def downgrade() -> None:
    op.drop_index("ix_chunks_content_hash", table_name="chunks", schema="knowledge")
    op.drop_index("ix_chunks_ingestion_item_id", table_name="chunks", schema="knowledge")
    op.drop_table("chunks", schema="knowledge")
