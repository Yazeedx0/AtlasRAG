"""add knowledge chunks table

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-06

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
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ingestion_item_id", sa.UUID(), nullable=False),
        sa.Column("parent_chunk_id", sa.UUID(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "content_type",
            sa.Enum(
                "text",
                "table",
                "code",
                "other",
                name="chunk_content_type",
                schema="knowledge",
            ),
            server_default=sa.text("'text'"),
            nullable=False,
        ),
        sa.Column("section_title", sa.String(length=500), nullable=True),
        sa.Column(
            "section_path",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("language_code", sa.String(length=20), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint("chunk_index >= 0", name=op.f("ck_chunks_chunk_index_non_negative")),
        sa.CheckConstraint("token_count > 0", name=op.f("ck_chunks_token_count_positive")),
        sa.CheckConstraint(
            "length(btrim(content)) > 0",
            name=op.f("ck_chunks_content_not_blank"),
        ),
        sa.CheckConstraint(
            "page_start IS NULL OR page_end IS NULL OR page_end >= page_start",
            name=op.f("ck_chunks_valid_page_range"),
        ),
        sa.CheckConstraint(
            "parent_chunk_id IS NULL OR parent_chunk_id <> id",
            name=op.f("ck_chunks_parent_is_not_self"),
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_item_id"],
            ["knowledge.ingestion_items.id"],
            name=op.f("fk_chunks_ingestion_item_id_ingestion_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_chunk_id"],
            ["knowledge.chunks.id"],
            name=op.f("fk_chunks_parent_chunk_id_chunks"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint(
            "ingestion_item_id",
            "chunk_index",
            name="uq_chunks_item_chunk_index",
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_chunks_content_hash",
        "chunks",
        ["content_hash"],
        unique=False,
        schema="knowledge",
    )
    op.create_index(
        "ix_chunks_parent_chunk_id",
        "chunks",
        ["parent_chunk_id"],
        unique=False,
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_parent_chunk_id", table_name="chunks", schema="knowledge")
    op.drop_index("ix_chunks_content_hash", table_name="chunks", schema="knowledge")
    op.drop_table("chunks", schema="knowledge")
    sa.Enum(name="chunk_content_type", schema="knowledge").drop(op.get_bind())
