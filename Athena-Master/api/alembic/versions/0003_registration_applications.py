"""registration applications and access nodes

Revision ID: 0003_registration_applications
Revises: 0002_user_auth_version
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_registration_applications"
down_revision = "0002_user_auth_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_applications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("reported_name", sa.String(length=100), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("software_version", sa.String(length=64), nullable=False),
        sa.Column("raw_body", sa.LargeBinary(), nullable=False),
        sa.Column("request_path", sa.String(length=255), nullable=False),
        sa.Column("auth_timestamp", sa.String(length=20), nullable=False),
        sa.Column("auth_nonce", sa.String(length=32), nullable=False),
        sa.Column("auth_signature", sa.String(length=64), nullable=False),
        sa.Column("source_ip", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_registration_applications_node_id",
        "registration_applications",
        ["node_id"],
    )
    op.create_table(
        "access_nodes",
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("reported_name", sa.String(length=100), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("software_version", sa.String(length=64), nullable=False),
        sa.Column(
            "management_status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
        sa.Column("encrypted_token", sa.String(length=512), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("node_id"),
    )


def downgrade() -> None:
    op.drop_table("access_nodes")
    op.drop_index(
        "ix_registration_applications_node_id",
        table_name="registration_applications",
    )
    op.drop_table("registration_applications")
