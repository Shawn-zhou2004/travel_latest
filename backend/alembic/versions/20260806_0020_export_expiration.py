"""Add durable expiration facts for generated export outputs.

Revision ID: 20260806_0020
Revises: 20260806_0019
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260806_0020"
down_revision = "20260806_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("export_tasks", sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=True))
    # Preserve the seven-day retention policy for outputs generated before deployment.
    op.execute(
        "UPDATE export_tasks "
        "SET expires_at = DATE_ADD(COALESCE(finished_at, updated_at, created_at), INTERVAL 7 DAY) "
        "WHERE status = 'succeeded'"
    )
    op.execute(
        "UPDATE media_assets AS asset "
        "JOIN export_tasks AS task ON task.output_asset_id = asset.id "
        "SET asset.upload_expires_at = task.expires_at "
        "WHERE task.status = 'succeeded'"
    )
    op.create_index("ix_export_tasks_status_expires_at", "export_tasks", ["status", "expires_at"])
    op.drop_constraint("ck_export_tasks_status", "export_tasks", type_="check")
    op.create_check_constraint(
        "ck_export_tasks_status",
        "export_tasks",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired')",
    )


def downgrade() -> None:
    op.execute("UPDATE export_tasks SET status = 'succeeded' WHERE status = 'expired'")
    op.drop_constraint("ck_export_tasks_status", "export_tasks", type_="check")
    op.create_check_constraint(
        "ck_export_tasks_status",
        "export_tasks",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
    )
    op.drop_index("ix_export_tasks_status_expires_at", table_name="export_tasks")
    op.drop_column("export_tasks", "expires_at")
