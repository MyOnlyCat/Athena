"""Add operation audit logs.

Revision ID: 0008_operation_audit
Revises: 0007_node_lifecycle_management
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_operation_audit"
down_revision = "0007_node_lifecycle_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36)),
        sa.Column("actor_username", sa.String(64)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(255)),
        sa.Column("target_label", sa.String(255)),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("source_ip", sa.String(255)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_table("audit_logs")
