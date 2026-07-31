"""registration lifecycle protections

Revision ID: 0004_registration_lifecycle
Revises: 0003_registration_applications
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_registration_lifecycle"
down_revision = "0003_registration_applications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "registration_applications",
        sa.Column("rejection_reason", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "registration_applications",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE registration_applications "
        "SET status_changed_at = received_at WHERE status_changed_at IS NULL"
    )
    with op.batch_alter_table("registration_applications") as batch:
        batch.alter_column("status_changed_at", nullable=False)
    with op.batch_alter_table("access_nodes") as batch:
        batch.add_column(
            sa.Column("token_fingerprint", sa.String(length=64), nullable=True),
        )
        batch.create_unique_constraint(
            "uq_access_nodes_token_fingerprint",
            ["token_fingerprint"],
        )


def downgrade() -> None:
    with op.batch_alter_table("access_nodes") as batch:
        batch.drop_constraint(
            "uq_access_nodes_token_fingerprint",
            type_="unique",
        )
        batch.drop_column("token_fingerprint")
    op.drop_column("registration_applications", "status_changed_at")
    op.drop_column("registration_applications", "rejection_reason")
