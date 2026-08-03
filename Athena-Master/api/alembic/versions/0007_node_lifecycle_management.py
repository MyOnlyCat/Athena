"""Add administrator-owned node lifecycle fields.

Revision ID: 0007_node_lifecycle_management
Revises: 0006_host_asset_snapshots
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0007_node_lifecycle_management"
down_revision = "0006_host_asset_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_nodes", sa.Column("display_name", sa.String(100)))
    op.add_column("access_nodes", sa.Column("notes", sa.String(1000)))
    op.add_column(
        "access_nodes",
        sa.Column(
            "management_tags",
            sa.JSON(),
            nullable=False,
            server_default=json.dumps([]),
        ),
    )
    op.add_column("access_nodes", sa.Column("disable_reason", sa.String(1000)))


def downgrade() -> None:
    op.drop_column("access_nodes", "disable_reason")
    op.drop_column("access_nodes", "management_tags")
    op.drop_column("access_nodes", "notes")
    op.drop_column("access_nodes", "display_name")
