"""empty message

Revision ID: c525fcb7c817
Revises:
Create Date: 2026-08-19 00:27:34.244990

"""

from collections.abc import Sequence

revision: str = "c525fcb7c817"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
