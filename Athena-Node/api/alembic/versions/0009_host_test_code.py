"""Persist the standard SSH test result code."""

import sqlalchemy as sa

from alembic import op

revision = "0009_host_test_code"
down_revision = "0008_registration_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("last_test_code", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE hosts SET last_test_code = CASE "
            "WHEN last_test_status = 'success' THEN 'SSH_CONNECTED' "
            "WHEN last_test_status = 'pending_trust' THEN 'SSH_HOST_KEY_UNTRUSTED' "
            "WHEN last_test_message = 'SSH 认证失败' THEN 'SSH_AUTH_FAILED' "
            "WHEN last_test_message = 'SSH 连接超时' THEN 'SSH_TIMEOUT' "
            "WHEN last_test_message = 'SSH 连接失败' THEN 'SSH_CONNECTION_FAILED' "
            "WHEN last_test_message IN ('SSH 主机指纹已变更', 'SSH 主机指纹已变化') "
            "THEN 'SSH_HOST_KEY_CHANGED' END"
        )
    )
    op.execute(
        sa.text(
            "UPDATE hosts SET last_test_status = NULL, last_tested_at = NULL "
            "WHERE last_test_status IS NOT NULL AND last_test_code IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("hosts", "last_test_code")
