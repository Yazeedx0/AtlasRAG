"""add group memberships table

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "group_memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "group_principal_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column("member_principal_id", sa.UUID(), nullable=False),
        sa.Column(
            "member_type",
            postgresql.ENUM(
                "user",
                "role",
                "group",
                name="principal_type",
                schema="iam",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("added_by_principal_id", sa.UUID(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by_principal_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "member_type IN ('user', 'group')",
            name=op.f("ck_group_memberships_member_type_user_or_group"),
        ),
        sa.CheckConstraint(
            "group_principal_id != member_principal_id",
            name=op.f("ck_group_memberships_no_self_membership"),
        ),
        sa.CheckConstraint(
            "removed_at IS NULL OR removed_at >= added_at",
            name=op.f("ck_group_memberships_removed_not_before_added"),
        ),
        sa.ForeignKeyConstraint(
            ["group_principal_id"],
            ["iam.groups.principal_id"],
            name=op.f("fk_group_memberships_group_principal_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_principal_id", "member_type"],
            ["iam.principals.id", "iam.principals.type"],
            name=op.f("fk_group_memberships_member_principal_id_principals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_group_memberships_added_by_principal_id_principals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["removed_by_principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_group_memberships_removed_by_principal_id_principals"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_group_memberships")),
        schema="iam",
    )
    op.create_index(
        "ix_group_memberships_group_principal_id",
        "group_memberships",
        ["group_principal_id"],
        unique=False,
        schema="iam",
    )
    op.create_index(
        "ix_group_memberships_member_principal_id",
        "group_memberships",
        ["member_principal_id"],
        unique=False,
        schema="iam",
    )
    op.create_index(
        "ix_group_memberships_member_principal_type",
        "group_memberships",
        ["member_principal_id", "member_type"],
        unique=False,
        schema="iam",
    )
    op.create_index(
        "uq_group_memberships_active_membership",
        "group_memberships",
        ["group_principal_id", "member_principal_id"],
        unique=True,
        schema="iam",
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_group_memberships_active_membership",
        table_name="group_memberships",
        schema="iam",
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.drop_index(
        "ix_group_memberships_member_principal_type",
        table_name="group_memberships",
        schema="iam",
    )
    op.drop_index(
        "ix_group_memberships_member_principal_id",
        table_name="group_memberships",
        schema="iam",
    )
    op.drop_index(
        "ix_group_memberships_group_principal_id",
        table_name="group_memberships",
        schema="iam",
    )
    op.drop_table("group_memberships", schema="iam")
