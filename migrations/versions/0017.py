"""retain document descriptive-field ownership in revision 0012

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-30

"""

from collections.abc import Sequence

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # These fields are owned by revision 0012, which creates the documents table.
    return None


def downgrade() -> None:
    return None
