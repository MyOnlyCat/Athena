"""Create encrypted singleton master settings table."""

import sqlalchemy as sa

from alembic import op

revision = "0005_master_settings"
down_revision = "0004_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "master_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme", sa.String(8), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("encrypted_token", sa.String(2048)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_master_settings_singleton"),
    )


def downgrade() -> None:
    op.drop_table("master_settings")
