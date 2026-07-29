"""Create deployment task, target, and event tables."""

import sqlalchemy as sa

from alembic import op

revision = "0003_deployments"
down_revision = "0002_hosts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("master_task_id", sa.String(128), nullable=False, unique=True),
        sa.Column("artifact_url", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index(
        "ix_deployment_tasks_master_task_id",
        "deployment_tasks",
        ["master_task_id"],
        unique=True,
    )
    op.create_index(
        "ix_deployment_tasks_status",
        "deployment_tasks",
        ["status"],
    )
    op.create_table(
        "deployment_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("deployment_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "host_id",
            sa.String(36),
            sa.ForeignKey("hosts.id", ondelete="SET NULL"),
        ),
        sa.Column("target_ip", sa.String(255), nullable=False),
        sa.Column("target_directory", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_deployment_targets_task_id", "deployment_targets", ["task_id"])
    op.create_index("ix_deployment_targets_status", "deployment_targets", ["status"])
    op.create_table(
        "deployment_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(128), nullable=False),
        sa.Column("target_id", sa.String(36)),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("task_id", "sequence"),
    )
    op.create_index("ix_deployment_events_task_id", "deployment_events", ["task_id"])


def downgrade() -> None:
    op.drop_table("deployment_events")
    op.drop_table("deployment_targets")
    op.drop_table("deployment_tasks")
