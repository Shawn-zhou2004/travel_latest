"""Create durable administrator search-index rebuild jobs.

Revision ID: 20260809_0031
Revises: 20260809_0030
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260809_0031"
down_revision = "20260809_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "search_index_rebuild_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("index_name", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("started_at", timestamp, nullable=True),
        sa.Column("completed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_search_index_rebuild_status"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_search_index_rebuild_progress"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name="fk_search_index_rebuild_requested_by"),
        sa.PrimaryKeyConstraint("id", name="pk_search_index_rebuild_jobs"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_search_index_rebuild_jobs_requested_by", "search_index_rebuild_jobs", ["requested_by"])
    op.create_index("ix_search_index_rebuild_jobs_status", "search_index_rebuild_jobs", ["status"])
    op.create_index("ix_search_index_rebuild_index_status", "search_index_rebuild_jobs", ["index_name", "status"])


def downgrade() -> None:
    op.drop_table("search_index_rebuild_jobs")
