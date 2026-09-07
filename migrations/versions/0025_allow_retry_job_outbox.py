"""allow a new outbox record for each ingestion retry

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-04

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_job_outbox_type_aggregate",
        "job_outbox",
        schema="platform",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_job_outbox_type_aggregate",
        "job_outbox",
        ["job_type", "aggregate_id"],
        schema="platform",
    )
