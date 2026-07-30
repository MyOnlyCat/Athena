"""Create singleton host probe settings table."""

import sqlalchemy as sa

from alembic import op

revision = "0006_host_probe_settings"
down_revision = "0005_master_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "host_probe_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_host_probe_settings_singleton"),
        sa.CheckConstraint(
            "interval_minutes >= 1 AND interval_minutes <= 1440",
            name="ck_host_probe_interval_minutes",
        ),
    )


def downgrade() -> None:
    op.drop_table("host_probe_settings")
