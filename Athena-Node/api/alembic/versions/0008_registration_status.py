"""Track the latest access registration state."""

import sqlalchemy as sa

from alembic import op

revision = "0008_registration_status"
down_revision = "0007_node_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "master_settings",
        sa.Column(
            "registration_status",
            sa.String(length=20),
            server_default="not_submitted",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("master_settings", "registration_status")
