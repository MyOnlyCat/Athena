"""Store current host asset snapshots for each access node.

Revision ID: 0006_host_asset_snapshots
Revises: 0005_authenticated_heartbeats
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_host_asset_snapshots"
down_revision = "0005_authenticated_heartbeats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "host_assets",
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("host_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("is_local", sa.Boolean(), nullable=False),
        sa.Column("last_test_status", sa.String(length=32), nullable=True),
        sa.Column("last_test_code", sa.String(length=64), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["access_nodes.node_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("node_id", "host_id"),
    )
    op.create_index("ix_host_assets_name", "host_assets", ["name"])
    op.create_index("ix_host_assets_address", "host_assets", ["address"])
    op.create_index("ix_host_assets_retired_at", "host_assets", ["retired_at"])


def downgrade() -> None:
    op.drop_index("ix_host_assets_retired_at", table_name="host_assets")
    op.drop_index("ix_host_assets_address", table_name="host_assets")
    op.drop_index("ix_host_assets_name", table_name="host_assets")
    op.drop_table("host_assets")
