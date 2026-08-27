"""Add durable generation attempt metadata.

Revision ID: 20260806_0015
Revises: 20260806_0014
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260806_0015"
down_revision = "20260806_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.add_column("generation_jobs", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("generation_jobs", sa.Column("last_attempt_at", timestamp, nullable=True))
    op.add_column("generation_jobs", sa.Column("last_error_code", sa.String(64), nullable=True))
    op.add_column("generation_jobs", sa.Column("last_error_message", sa.String(500), nullable=True))
    op.add_column("generation_jobs", sa.Column("trace_id", sa.String(36), nullable=True))
    op.add_column("generation_jobs", sa.Column("finished_at", timestamp, nullable=True))
    op.create_index("ix_generation_jobs_trace_id", "generation_jobs", ["trace_id"])
    op.create_check_constraint(
        "ck_generation_jobs_attempt_count",
        "generation_jobs",
        "attempt_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_generation_jobs_attempt_count", "generation_jobs", type_="check")
    op.drop_index("ix_generation_jobs_trace_id", table_name="generation_jobs")
    op.drop_column("generation_jobs", "finished_at")
    op.drop_column("generation_jobs", "trace_id")
    op.drop_column("generation_jobs", "last_error_message")
    op.drop_column("generation_jobs", "last_error_code")
    op.drop_column("generation_jobs", "last_attempt_at")
    op.drop_column("generation_jobs", "attempt_count")
