"""make all embedding model identity fields immutable and unique

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_embedding_models_identity",
        "embedding_models",
        schema="knowledge",
        type_="unique",
    )
    op.create_index(
        "uq_embedding_models_identity",
        "embedding_models",
        [
            "provider",
            "model_name",
            "model_revision",
            "dimension",
            "distance_metric",
            sa.text("COALESCE(max_input_tokens, -1)"),
            "configuration_hash",
        ],
        unique=True,
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_embedding_models_identity",
        table_name="embedding_models",
        schema="knowledge",
    )
    op.create_unique_constraint(
        "uq_embedding_models_identity",
        "embedding_models",
        ["provider", "model_name", "model_revision", "configuration_hash"],
        schema="knowledge",
    )
