"""Create versioned itinerary aggregate tables.

Revision ID: 20260801_0002
Revises: 20260801_0001
Create Date: 2026-08-01 00:02:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260801_0002"
down_revision = "20260801_0001"
branch_labels = None
depends_on = None


def _options() -> dict[str, str]:
    return {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    json = mysql.JSON()
    op.create_table("itineraries", sa.Column("id", sa.String(36), nullable=False), sa.Column("owner_id", sa.String(36), nullable=False), sa.Column("title", sa.String(160), nullable=False), sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("status", sa.String(32), nullable=False, server_default="draft"), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("version >= 1", name="ck_itineraries_version"), sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_itineraries_owner_id_users"), sa.PrimaryKeyConstraint("id", name="pk_itineraries"), **_options())
    op.create_index("ix_itineraries_owner_id", "itineraries", ["owner_id"])
    op.create_table("itinerary_days", sa.Column("id", sa.String(36), nullable=False), sa.Column("itinerary_id", sa.String(36), nullable=False), sa.Column("day_date", sa.Date(), nullable=False), sa.Column("display_order", sa.Integer(), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], name="fk_itinerary_days_itinerary_id_itineraries", ondelete="CASCADE"), sa.PrimaryKeyConstraint("id", name="pk_itinerary_days"), sa.UniqueConstraint("itinerary_id", "day_date", name="uq_itinerary_days_date"), sa.UniqueConstraint("itinerary_id", "display_order", name="uq_itinerary_days_display_order"), **_options())
    op.create_index("ix_itinerary_days_itinerary_id", "itinerary_days", ["itinerary_id"])
    op.create_table("itinerary_events", sa.Column("id", sa.String(36), nullable=False), sa.Column("day_id", sa.String(36), nullable=False), sa.Column("poi_id", sa.String(128), nullable=False), sa.Column("poi_snapshot", json, nullable=False), sa.Column("starts_at", timestamp), sa.Column("ends_at", timestamp), sa.Column("display_order", sa.Integer(), nullable=False), sa.Column("notes", sa.Text()), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("display_order >= 0", name="ck_itinerary_events_display_order"), sa.ForeignKeyConstraint(["day_id"], ["itinerary_days.id"], name="fk_itinerary_events_day_id_itinerary_days", ondelete="CASCADE"), sa.PrimaryKeyConstraint("id", name="pk_itinerary_events"), sa.UniqueConstraint("day_id", "display_order", name="uq_itinerary_events_display_order"), **_options())
    op.create_index("ix_itinerary_events_day_id", "itinerary_events", ["day_id"])
    op.create_table("itinerary_versions", sa.Column("id", sa.String(36), nullable=False), sa.Column("itinerary_id", sa.String(36), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("snapshot", json, nullable=False), sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], name="fk_itinerary_versions_itinerary_id_itineraries", ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_itinerary_versions_created_by_users"), sa.PrimaryKeyConstraint("id", name="pk_itinerary_versions"), sa.UniqueConstraint("itinerary_id", "version", name="uq_itinerary_versions_version"), **_options())
    op.create_index("ix_itinerary_versions_itinerary_id", "itinerary_versions", ["itinerary_id"])
    op.create_table("route_segments", sa.Column("id", sa.String(36), nullable=False), sa.Column("day_id", sa.String(36), nullable=False), sa.Column("display_order", sa.Integer(), nullable=False), sa.Column("travel_mode", sa.String(32), nullable=False), sa.Column("distance_meters", sa.Integer()), sa.Column("duration_seconds", sa.Integer()), sa.Column("route_snapshot", json), sa.Column("source_updated_at", timestamp), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.ForeignKeyConstraint(["day_id"], ["itinerary_days.id"], name="fk_route_segments_day_id_itinerary_days", ondelete="CASCADE"), sa.PrimaryKeyConstraint("id", name="pk_route_segments"), sa.UniqueConstraint("day_id", "display_order", name="uq_route_segments_display_order"), **_options())
    op.create_index("ix_route_segments_day_id", "route_segments", ["day_id"])
    op.create_table("trip_collaborators", sa.Column("id", sa.String(36), nullable=False), sa.Column("itinerary_id", sa.String(36), nullable=False), sa.Column("user_id", sa.String(36), nullable=False), sa.Column("role", sa.String(16), nullable=False), sa.Column("status", sa.String(16), nullable=False, server_default="pending"), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("role IN ('viewer', 'editor')", name="ck_trip_collaborators_role"), sa.CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="ck_trip_collaborators_status"), sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], name="fk_trip_collaborators_itinerary_id_itineraries", ondelete="CASCADE"), sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_trip_collaborators_user_id_users"), sa.PrimaryKeyConstraint("id", name="pk_trip_collaborators"), sa.UniqueConstraint("itinerary_id", "user_id", name="uq_trip_collaborators_user"), **_options())
    op.create_index("ix_trip_collaborators_itinerary_id", "trip_collaborators", ["itinerary_id"])
    op.create_index("ix_trip_collaborators_user_id", "trip_collaborators", ["user_id"])
    op.create_table("trip_share_tokens", sa.Column("id", sa.String(36), nullable=False), sa.Column("itinerary_id", sa.String(36), nullable=False), sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("expires_at", timestamp), sa.Column("revoked_at", timestamp), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], name="fk_trip_share_tokens_itinerary_id_itineraries", ondelete="CASCADE"), sa.PrimaryKeyConstraint("id", name="pk_trip_share_tokens"), sa.UniqueConstraint("token_hash", name="uq_trip_share_tokens_hash"), **_options())
    op.create_index("ix_trip_share_tokens_itinerary_id", "trip_share_tokens", ["itinerary_id"])
    op.create_table("trip_operations", sa.Column("id", sa.String(36), nullable=False), sa.Column("itinerary_id", sa.String(36), nullable=False), sa.Column("operation_id", sa.String(128), nullable=False), sa.Column("actor_id", sa.String(36), nullable=False), sa.Column("operation_type", sa.String(64), nullable=False), sa.Column("base_version", sa.Integer(), nullable=False), sa.Column("result_version", sa.Integer(), nullable=False), sa.Column("result_snapshot", json, nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], name="fk_trip_operations_itinerary_id_itineraries", ondelete="CASCADE"), sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name="fk_trip_operations_actor_id_users"), sa.PrimaryKeyConstraint("id", name="pk_trip_operations"), sa.UniqueConstraint("itinerary_id", "operation_id", name="uq_trip_operations_operation"), **_options())
    op.create_index("ix_trip_operations_itinerary_id", "trip_operations", ["itinerary_id"])


def downgrade() -> None:
    op.drop_table("trip_operations")
    op.drop_table("trip_share_tokens")
    op.drop_table("trip_collaborators")
    op.drop_table("route_segments")
    op.drop_table("itinerary_versions")
    op.drop_table("itinerary_events")
    op.drop_table("itinerary_days")
    op.drop_table("itineraries")
