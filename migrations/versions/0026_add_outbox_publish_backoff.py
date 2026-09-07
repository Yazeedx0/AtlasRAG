"""add publish backoff scheduling to job outbox

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PENDING_PREDICATE = "published_at IS NULL AND failed_at IS NULL"


def upgrade() -> None:
    op.add_column(
        "job_outbox",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_check_constraint(
        op.f("ck_job_outbox_terminal_job_has_no_next_attempt"),
        "job_outbox",
        "next_attempt_at IS NULL OR (published_at IS NULL AND failed_at IS NULL)",
        schema="platform",
    )
    op.create_index(
        "ix_job_outbox_unpublished_next_attempt_at",
        "job_outbox",
        ["next_attempt_at"],
        unique=False,
        schema="platform",
        postgresql_where=sa.text(_PENDING_PREDICATE),
    )
    op.create_index(
        "ix_job_outbox_dead_lettered_failed_at",
        "job_outbox",
        ["failed_at"],
        unique=False,
        schema="platform",
        postgresql_where=sa.text("failed_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_outbox_dead_lettered_failed_at",
        table_name="job_outbox",
        schema="platform",
    )
    op.drop_index(
        "ix_job_outbox_unpublished_next_attempt_at",
        table_name="job_outbox",
        schema="platform",
    )
    op.drop_constraint(
        op.f("ck_job_outbox_terminal_job_has_no_next_attempt"),
        "job_outbox",
        schema="platform",
        type_="check",
    )
    op.drop_column("job_outbox", "next_attempt_at", schema="platform")
