"""Create AI generation job facts.

Revision ID: 20260805_0010
Revises: 20260804_0009
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260805_0010"
down_revision = "20260804_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("target_itinerary_id", sa.String(36), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("city_code", sa.String(32), nullable=False),
        sa.Column("prompt", sa.String(2000), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("request_json", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome", sa.String(24), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("preview_id", sa.String(36), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('queued', 'understanding', 'retrieving', 'planning', 'validating', 'awaiting_confirmation', 'succeeded', 'failed', 'cancelled')", name="ck_generation_jobs_status"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('preview', 'no_result', 'clarification', 'unavailable')", name="ck_generation_jobs_outcome"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_generation_jobs_progress"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_generation_jobs_user_id_users"),
        sa.ForeignKeyConstraint(["target_itinerary_id"], ["itineraries.id"], ondelete="SET NULL", name="fk_generation_jobs_target_itinerary_id_itineraries"),
        sa.PrimaryKeyConstraint("id", name="pk_generation_jobs"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_generation_jobs_user_key"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_generation_jobs_user_id", "generation_jobs", ["user_id"])
    op.create_index("ix_generation_jobs_target_itinerary_id", "generation_jobs", ["target_itinerary_id"])
    op.create_index("ix_generation_jobs_city_code", "generation_jobs", ["city_code"])
    op.create_index("ix_generation_jobs_status", "generation_jobs", ["status"])
    op.create_index("ix_generation_jobs_preview_id", "generation_jobs", ["preview_id"])


def downgrade() -> None:
    op.drop_table("generation_jobs")
