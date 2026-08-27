"""Add reviewed POI recommendation candidates.

Revision ID: 20260811_0036
Revises: 20260811_0035
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260811_0036"
down_revision = "20260811_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "poi_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("poi_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.String(500), nullable=False, server_default=""),
        sa.Column("city_code", sa.String(32), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("amap_type", sa.String(255)),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("admin_weight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovery_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_itinerary_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_reason", sa.String(500)),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6)),
        sa.Column("official_knowledge_source_id", sa.String(36)),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("status IN ('pending_review', 'approved', 'rejected', 'retired')", name="ck_poi_candidate_status"),
        sa.CheckConstraint("admin_weight >= 0 AND admin_weight <= 100", name="ck_poi_candidate_admin_weight"),
        sa.CheckConstraint("discovery_count >= 0", name="ck_poi_candidate_discovery_count"),
        sa.CheckConstraint("confirmed_itinerary_count >= 0", name="ck_poi_candidate_confirmed_count"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["official_knowledge_source_id"], ["official_knowledge_sources.id"]),
        sa.UniqueConstraint("poi_id", name="uq_poi_candidates_poi_id"),
        sa.UniqueConstraint("official_knowledge_source_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_poi_candidates_city_code", "poi_candidates", ["city_code"])
    op.create_index("ix_poi_candidates_status", "poi_candidates", ["status"])
    op.create_index("ix_poi_candidates_city_status_rank", "poi_candidates", ["city_code", "status", "admin_weight", "confirmed_itinerary_count", "discovery_count"])


def downgrade() -> None:
    op.drop_table("poi_candidates")
