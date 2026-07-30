"""Create encrypted SSH host table."""

import sqlalchemy as sa

from alembic import op

revision = "0002_hosts"
down_revision = "0001_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("encrypted_password", sa.String(1024), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("is_local", sa.Boolean(), nullable=False),
        sa.Column("host_key_fingerprint", sa.String(128)),
        sa.Column("last_test_status", sa.String(32)),
        sa.Column("last_test_message", sa.String(255)),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("address"),
    )
    op.create_index("ix_hosts_address", "hosts", ["address"], unique=True)
    op.create_index(
        "uq_hosts_single_local",
        "hosts",
        ["is_local"],
        unique=True,
        sqlite_where=sa.text("is_local = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_hosts_single_local", table_name="hosts")
    op.drop_index("ix_hosts_address", table_name="hosts")
    op.drop_table("hosts")
