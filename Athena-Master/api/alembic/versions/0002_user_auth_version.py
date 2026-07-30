"""Add administrator authentication version."""

import sqlalchemy as sa

from alembic import op

revision = "0002_user_auth_version"
down_revision = "0001_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "auth_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "auth_version")
