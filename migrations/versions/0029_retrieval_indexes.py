"""add lexical search vector and per-model vector indexes

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEARCH_VECTOR_EXPRESSION = (
    "to_tsvector("
    "CASE WHEN lower(coalesce(language_code, '')) ~ '^ar([-_]|$)' "
    "THEN 'arabic'::regconfig ELSE 'english'::regconfig END, content)"
)

_OPERATOR_CLASS_SUFFIX = {
    "cosine": "cosine_ops",
    "inner_product": "ip_ops",
    "euclidean": "l2_ops",
}


def _vector_index_type(dimension: int) -> str | None:
    if dimension <= 2000:
        return "vector"
    if dimension <= 4000:
        return "halfvec"
    return None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge.chunks ADD COLUMN search_vector tsvector "
        f"GENERATED ALWAYS AS ({_SEARCH_VECTOR_EXPRESSION}) STORED NOT NULL"
    )
    op.create_index(
        "ix_chunks_search_vector",
        "chunks",
        ["search_vector"],
        schema="knowledge",
        postgresql_using="gin",
    )

    models = op.get_bind().execute(
        sa.text("SELECT id, dimension, distance_metric FROM knowledge.embedding_models")
    )
    for model_id, dimension, distance_metric in models:
        index_type = _vector_index_type(dimension)
        if index_type is None:
            continue
        operator_class = f"{index_type}_{_OPERATOR_CLASS_SUFFIX[distance_metric]}"
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_hnsw_{model_id.hex} "
            "ON knowledge.chunk_embeddings "
            f"USING hnsw ((embedding::{index_type}({dimension})) {operator_class}) "
            f"WHERE embedding_model_id = '{model_id}'"
        )


def downgrade() -> None:
    models = op.get_bind().execute(sa.text("SELECT id FROM knowledge.embedding_models"))
    for (model_id,) in models:
        op.execute(f"DROP INDEX IF EXISTS knowledge.ix_chunk_embeddings_hnsw_{model_id.hex}")

    op.drop_index("ix_chunks_search_vector", table_name="chunks", schema="knowledge")
    op.drop_column("chunks", "search_vector", schema="knowledge")
