"""add application permission grants

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-30

"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = (
    {
        "permission_key": "iam.principals.manage",
        "description": "Manage principal lifecycle state.",
    },
    {
        "permission_key": "iam.roles.manage",
        "description": "Manage roles and role assignments.",
    },
    {
        "permission_key": "iam.groups.manage",
        "description": "Manage groups and group memberships.",
    },
    {
        "permission_key": "iam.permissions.manage",
        "description": "Manage application permission grants.",
    },
    {
        "permission_key": "knowledge.documents.manage",
        "description": "Manage knowledge documents.",
    },
    {
        "permission_key": "knowledge.document_acl.manage",
        "description": "Manage document access grants.",
    },
)

SUPERADMIN_ROLE_PRINCIPAL_ID = UUID("7f1ec96f-ae1b-4bc2-8f1d-840d8be90c4b")
SUPERADMIN_ROLE_KEY = "superadmin"
SUPERADMIN_GRANTED_AT = datetime(2026, 8, 30, tzinfo=timezone.utc)
SUPERADMIN_PERMISSION_GRANT_IDS = (
    UUID("4a49a8e6-e0de-4505-ac9d-3c1588967f70"),
    UUID("8b5ecf64-e7f7-4ea7-8fa0-d710e76b0203"),
    UUID("68180fd4-0387-46d7-a33d-f3cb50c14d6f"),
    UUID("f2a0a33a-e131-4c45-85a3-e5d7264d8f87"),
    UUID("2bc81442-5252-49de-8a66-05c934fa2a89"),
    UUID("a7683470-d46d-4f42-b46e-7a5983c07d0a"),
)


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("permission_key", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("permission_key", name=op.f("pk_permissions")),
        schema="iam",
    )
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("permission_key", sa.String(length=150)),
            sa.column("description", sa.Text()),
            schema="iam",
        ),
        list(PERMISSIONS),
    )

    op.create_table(
        "principal_permissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("permission_key", sa.String(length=150), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by_principal_id", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_principal_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name=op.f(
                "ck_principal_permissions_principal_permission_revoked_not_before_granted"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_principal_permissions_principal_id_principals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["permission_key"],
            ["iam.permissions.permission_key"],
            name=op.f("fk_principal_permissions_permission_key_permissions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_principal_permissions_granted_by_principal_id_principals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_principal_id"],
            ["iam.principals.id"],
            name=op.f("fk_principal_permissions_revoked_by_principal_id_principals"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_principal_permissions")),
        schema="iam",
    )
    op.create_index(
        "uq_principal_permissions_active",
        "principal_permissions",
        ["principal_id", "permission_key"],
        unique=True,
        schema="iam",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_principal_permissions_permission_key",
        "principal_permissions",
        ["permission_key"],
        unique=False,
        schema="iam",
    )

    existing_role_id = op.get_bind().scalar(
        sa.text(
            "SELECT principal_id FROM iam.roles WHERE role_key = :role_key"
        ).bindparams(role_key=SUPERADMIN_ROLE_KEY)
    )
    superadmin_role_id = (
        SUPERADMIN_ROLE_PRINCIPAL_ID
        if existing_role_id is None
        else UUID(str(existing_role_id))
    )

    if existing_role_id is None:
        op.bulk_insert(
            sa.table(
                "principals",
                sa.column("id", sa.UUID()),
                sa.column(
                    "type",
                    postgresql.ENUM(
                        "user",
                        "role",
                        "group",
                        name="principal_type",
                        schema="iam",
                        create_type=False,
                    ),
                ),
                sa.column("is_active", sa.Boolean()),
                schema="iam",
            ),
            [
                {
                    "id": superadmin_role_id,
                    "type": "role",
                    "is_active": True,
                }
            ],
        )
        op.bulk_insert(
            sa.table(
                "roles",
                sa.column("principal_id", sa.UUID()),
                sa.column("role_key", sa.String(length=100)),
                sa.column("name", sa.String(length=255)),
                sa.column("description", sa.Text()),
                schema="iam",
            ),
            [
                {
                    "principal_id": superadmin_role_id,
                    "role_key": SUPERADMIN_ROLE_KEY,
                    "name": "Superadmin",
                    "description": "Built-in role with every application capability.",
                }
            ],
        )
    op.bulk_insert(
        sa.table(
            "principal_permissions",
            sa.column("id", sa.UUID()),
            sa.column("principal_id", sa.UUID()),
            sa.column("permission_key", sa.String(length=150)),
            sa.column("granted_at", sa.DateTime(timezone=True)),
            schema="iam",
        ),
        [
            {
                "id": grant_id,
                "principal_id": superadmin_role_id,
                "permission_key": permission["permission_key"],
                "granted_at": SUPERADMIN_GRANTED_AT,
            }
            for grant_id, permission in zip(
                SUPERADMIN_PERMISSION_GRANT_IDS,
                PERMISSIONS,
                strict=True,
            )
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_principal_permissions_permission_key",
        table_name="principal_permissions",
        schema="iam",
    )
    op.drop_index(
        "uq_principal_permissions_active",
        table_name="principal_permissions",
        schema="iam",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_table("principal_permissions", schema="iam")
    op.drop_table("permissions", schema="iam")
    op.execute(
        "DELETE FROM iam.principals "
        "WHERE id = '7f1ec96f-ae1b-4bc2-8f1d-840d8be90c4b'"
    )
