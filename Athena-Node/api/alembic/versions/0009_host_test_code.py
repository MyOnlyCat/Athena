"""Persist the standard SSH test result code."""

import sqlalchemy as sa

from alembic import op

revision = "0009_host_test_code"
down_revision = "0008_registration_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("last_test_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hosts", "last_test_code")
