"""add terminal failure state to job outbox

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PENDING_PREDICATE = "published_at IS NULL AND failed_at IS NULL"


def upgrade() -> None:
    op.add_column(
        "job_outbox",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.add_column(
        "job_outbox",
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        schema="platform",
    )
    op.create_check_constraint(
        op.f("ck_job_outbox_failed_job_has_no_lease"),
        "job_outbox",
        "failed_at IS NULL OR lease_expires_at IS NULL",
        schema="platform",
    )
    op.create_check_constraint(
        op.f("ck_job_outbox_published_or_failed"),
        "job_outbox",
        "NOT (published_at IS NOT NULL AND failed_at IS NOT NULL)",
        schema="platform",
    )
    op.create_check_constraint(
        op.f("ck_job_outbox_terminal_failure_complete"),
        "job_outbox",
        "(failed_at IS NULL AND failure_code IS NULL) OR "
        "(failed_at IS NOT NULL AND failure_code IS NOT NULL "
        "AND length(btrim(failure_code)) > 0)",
        schema="platform",
    )

    op.drop_index(
        "ix_job_outbox_unpublished_created_at",
        table_name="job_outbox",
        schema="platform",
    )
    op.drop_index(
        "ix_job_outbox_unpublished_lease_expires_at",
        table_name="job_outbox",
        schema="platform",
    )
    op.create_index(
        "ix_job_outbox_unpublished_created_at",
        "job_outbox",
        ["created_at"],
        unique=False,
        schema="platform",
        postgresql_where=sa.text(_PENDING_PREDICATE),
    )
    op.create_index(
        "ix_job_outbox_unpublished_lease_expires_at",
        "job_outbox",
        ["lease_expires_at"],
        unique=False,
        schema="platform",
        postgresql_where=sa.text(_PENDING_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_outbox_unpublished_created_at",
        table_name="job_outbox",
        schema="platform",
    )
    op.drop_index(
        "ix_job_outbox_unpublished_lease_expires_at",
        table_name="job_outbox",
        schema="platform",
    )
    op.create_index(
        "ix_job_outbox_unpublished_created_at",
        "job_outbox",
        ["created_at"],
        unique=False,
        schema="platform",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index(
        "ix_job_outbox_unpublished_lease_expires_at",
        "job_outbox",
        ["lease_expires_at"],
        unique=False,
        schema="platform",
        postgresql_where=sa.text("published_at IS NULL"),
    )

    op.drop_constraint(
        op.f("ck_job_outbox_terminal_failure_complete"),
        "job_outbox",
        schema="platform",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_job_outbox_published_or_failed"),
        "job_outbox",
        schema="platform",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_job_outbox_failed_job_has_no_lease"),
        "job_outbox",
        schema="platform",
        type_="check",
    )
    op.drop_column("job_outbox", "failure_code", schema="platform")
    op.drop_column("job_outbox", "failed_at", schema="platform")
