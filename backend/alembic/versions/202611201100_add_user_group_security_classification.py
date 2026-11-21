"""Add a security level to user groups.

The column is empty after the upgrade, so nothing changes until an
administrator sets a level on a group. A removed classification empties it.

Revision ID: 202611201100
Revises: 202611201000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611201100"
down_revision: str | None = "202611201000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_groups",
        sa.Column(
            "security_classification_id",
            sa.UUID(),
            sa.ForeignKey("security_classifications.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_groups", "security_classification_id")
