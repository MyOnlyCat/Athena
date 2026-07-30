"""Persist the immutable access-node identity."""

import sqlalchemy as sa

from alembic import op

revision = "0007_node_identity"
down_revision = "0006_host_probe_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("reported_name", sa.String(length=100), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_node_identities_singleton"),
    )


def downgrade() -> None:
    op.drop_table("node_identities")
