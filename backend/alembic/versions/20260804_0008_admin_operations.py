"""Add administration audit and review state.

Revision ID: 20260804_0008
Revises: 20260804_0007
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260804_0008"
down_revision = "20260804_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.add_column("content_reports", sa.Column("status", sa.String(16), nullable=False, server_default="pending"))
    op.add_column("content_reports", sa.Column("resolution", sa.String(500), nullable=True))
    op.create_check_constraint("ck_content_reports_status", "content_reports", "status IN ('pending', 'resolved', 'dismissed')")
    op.add_column("companion_requests", sa.Column("review_status", sa.String(16), nullable=False, server_default="approved"))
    op.add_column("companion_requests", sa.Column("review_reason", sa.String(500), nullable=True))
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("result_json", mysql.JSON(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name="fk_admin_actions_actor_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_admin_actions"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index("ix_admin_actions_actor_id", "admin_actions", ["actor_id"])
    op.create_index("ix_admin_actions_target_id", "admin_actions", ["target_id"])


def downgrade() -> None:
    op.drop_table("admin_actions")
    op.drop_column("companion_requests", "review_reason")
    op.drop_column("companion_requests", "review_status")
    op.drop_constraint("ck_content_reports_status", "content_reports", type_="check")
    op.drop_column("content_reports", "resolution")
    op.drop_column("content_reports", "status")
