"""add embedding models, embedding runs and chunk embeddings

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_VECTOR_DIMENSION = 16000


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "embedding_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("model_revision", sa.String(length=100), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column(
            "distance_metric",
            sa.Enum(
                "cosine",
                "inner_product",
                "euclidean",
                name="vector_distance_metric",
                schema="knowledge",
            ),
            nullable=False,
        ),
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"dimension > 0 AND dimension <= {MAX_VECTOR_DIMENSION}",
            name=op.f("ck_embedding_models_valid_dimension"),
        ),
        sa.CheckConstraint(
            "max_input_tokens IS NULL OR max_input_tokens > 0",
            name=op.f("ck_embedding_models_max_input_tokens_positive"),
        ),
        sa.CheckConstraint(
            "length(btrim(model_name)) > 0",
            name=op.f("ck_embedding_models_model_name_non_empty"),
        ),
        sa.CheckConstraint(
            "length(btrim(model_revision)) > 0",
            name=op.f("ck_embedding_models_model_revision_non_empty"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_models")),
        sa.UniqueConstraint(
            "provider",
            "model_name",
            "model_revision",
            "configuration_hash",
            name="uq_embedding_models_identity",
        ),
        schema="knowledge",
    )

    op.create_table(
        "embedding_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                name="embedding_status",
                schema="knowledge",
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=150), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "execution_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_principal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_embedding_runs_attempt_count_non_negative"),
        ),
        sa.CheckConstraint(
            "status != 'running'"
            " OR (started_at IS NOT NULL"
            " AND claimed_at IS NOT NULL"
            " AND lease_expires_at IS NOT NULL)",
            name=op.f("ck_embedding_runs_running_requires_claim"),
        ),
        sa.CheckConstraint(
            "status = 'running' OR lease_expires_at IS NULL",
            name=op.f("ck_embedding_runs_lease_only_while_running"),
        ),
        sa.CheckConstraint(
            "lease_expires_at IS NULL"
            " OR (claimed_at IS NOT NULL"
            " AND lease_expires_at > claimed_at)",
            name=op.f("ck_embedding_runs_valid_lease"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('completed', 'failed') OR completed_at IS NOT NULL",
            name=op.f("ck_embedding_runs_terminal_requires_completed_at"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name=op.f("ck_embedding_runs_completed_not_before_started"),
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_item_id"],
            ["knowledge.ingestion_items.id"],
            name=op.f("fk_embedding_runs_ingestion_item_id_ingestion_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["knowledge.embedding_models.id"],
            name=op.f("fk_embedding_runs_embedding_model_id_embedding_models"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_embedding_runs_created_by_principal_id_principals"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_runs")),
        schema="knowledge",
    )
    op.create_index(
        "uq_embedding_runs_in_flight",
        "embedding_runs",
        ["ingestion_item_id", "embedding_model_id"],
        unique=True,
        schema="knowledge",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_index(
        "ix_embedding_runs_ingestion_item_id",
        "embedding_runs",
        ["ingestion_item_id"],
        schema="knowledge",
    )
    op.create_index(
        "ix_embedding_runs_embedding_model_id",
        "embedding_runs",
        ["embedding_model_id"],
        schema="knowledge",
    )
    op.create_index(
        "ix_embedding_runs_status",
        "embedding_runs",
        ["status"],
        schema="knowledge",
    )
    op.create_index(
        "ix_embedding_runs_expired_running_lease",
        "embedding_runs",
        ["lease_expires_at"],
        schema="knowledge",
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"dimension > 0 AND dimension <= {MAX_VECTOR_DIMENSION}",
            name=op.f("ck_chunk_embeddings_valid_dimension"),
        ),
        sa.CheckConstraint(
            "vector_dims(embedding) = dimension",
            name=op.f("ck_chunk_embeddings_embedding_matches_dimension"),
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["knowledge.chunks.id"],
            name=op.f("fk_chunk_embeddings_chunk_id_chunks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["knowledge.embedding_models.id"],
            name=op.f("fk_chunk_embeddings_embedding_model_id_embedding_models"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_run_id"],
            ["knowledge.embedding_runs.id"],
            name=op.f("fk_chunk_embeddings_embedding_run_id_embedding_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("chunk_id", "embedding_model_id", name="pk_chunk_embeddings"),
        schema="knowledge",
    )
    op.create_index(
        "ix_chunk_embeddings_embedding_model_id",
        "chunk_embeddings",
        ["embedding_model_id"],
        schema="knowledge",
    )
    op.create_index(
        "ix_chunk_embeddings_embedding_run_id",
        "chunk_embeddings",
        ["embedding_run_id"],
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chunk_embeddings_embedding_run_id",
        table_name="chunk_embeddings",
        schema="knowledge",
    )
    op.drop_index(
        "ix_chunk_embeddings_embedding_model_id",
        table_name="chunk_embeddings",
        schema="knowledge",
    )
    op.drop_table("chunk_embeddings", schema="knowledge")

    op.drop_index(
        "ix_embedding_runs_expired_running_lease",
        table_name="embedding_runs",
        schema="knowledge",
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index("ix_embedding_runs_status", table_name="embedding_runs", schema="knowledge")
    op.drop_index(
        "ix_embedding_runs_embedding_model_id",
        table_name="embedding_runs",
        schema="knowledge",
    )
    op.drop_index(
        "ix_embedding_runs_ingestion_item_id",
        table_name="embedding_runs",
        schema="knowledge",
    )
    op.drop_index(
        "uq_embedding_runs_in_flight",
        table_name="embedding_runs",
        schema="knowledge",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.drop_table("embedding_runs", schema="knowledge")
    op.drop_table("embedding_models", schema="knowledge")

    sa.Enum(name="embedding_status", schema="knowledge").drop(op.get_bind())
    sa.Enum(name="vector_distance_metric", schema="knowledge").drop(op.get_bind())
