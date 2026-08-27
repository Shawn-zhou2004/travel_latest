"""Add asynchronous itinerary route calculation jobs.

Revision ID: 20260804_0007
Revises: 20260804_0006
Create Date: 2026-08-04 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260804_0007"
down_revision = "20260804_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "route_calculation_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("itinerary_id", sa.String(length=36), nullable=False),
        sa.Column("day_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by", sa.String(length=36), nullable=False),
        sa.Column("event_ids", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("completed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('queued', 'calculating', 'completed', 'failed')", name="ck_route_calculation_jobs_status"),
        sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], name="fk_route_calculation_jobs_itinerary_id_itineraries", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["day_id"], ["itinerary_days.id"], name="fk_route_calculation_jobs_day_id_itinerary_days", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name="fk_route_calculation_jobs_requested_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_route_calculation_jobs"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_route_calculation_jobs_itinerary_id", "route_calculation_jobs", ["itinerary_id"])
    op.create_index("ix_route_calculation_jobs_day_id", "route_calculation_jobs", ["day_id"])


def downgrade() -> None:
    op.drop_table("route_calculation_jobs")
