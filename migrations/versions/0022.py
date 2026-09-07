"""add transactional job outbox

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS platform")
    op.create_table(
        "job_outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.UUID(), nullable=False),
        sa.Column(
            "payload",
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
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_job_outbox_attempt_count_non_negative"),
        ),
        sa.CheckConstraint(
            "lease_expires_at IS NULL OR (claimed_at IS NOT NULL "
            "AND lease_expires_at > claimed_at)",
            name=op.f("ck_job_outbox_valid_publish_lease"),
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR lease_expires_at IS NULL",
            name=op.f("ck_job_outbox_published_job_has_no_lease"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_outbox")),
        sa.UniqueConstraint(
            "job_type",
            "aggregate_id",
            name="uq_job_outbox_type_aggregate",
        ),
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


def downgrade() -> None:
    op.drop_table("job_outbox", schema="platform")
