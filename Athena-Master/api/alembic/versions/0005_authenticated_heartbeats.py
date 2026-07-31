"""authenticated heartbeats and persistent nonce replay protection

Revision ID: 0005_authenticated_heartbeats
Revises: 0004_registration_lifecycle
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_authenticated_heartbeats"
down_revision = "0004_registration_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "access_nodes",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "node_nonces",
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("nonce", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["access_nodes.node_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("node_id", "nonce"),
    )
    op.create_index(
        "ix_node_nonces_received_at",
        "node_nonces",
        ["received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_node_nonces_received_at", table_name="node_nonces")
    op.drop_table("node_nonces")
    op.drop_column("access_nodes", "last_heartbeat_at")
