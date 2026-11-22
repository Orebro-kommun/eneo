"""Add a default security level for the organisation's users.

The column is empty after the upgrade, so nothing changes until an
administrator sets a level. A removed classification empties it.

Revision ID: 202611201000
Revises: 202611190900
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611201000"
down_revision: str | None = "202611190900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "default_user_security_classification_id",
            sa.UUID(),
            sa.ForeignKey("security_classifications.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "default_user_security_classification_id")
