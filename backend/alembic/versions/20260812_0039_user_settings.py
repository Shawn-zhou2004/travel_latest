"""Add persistent personal user settings.

Revision ID: 20260812_0039
Revises: 20260812_0038
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260812_0039"
down_revision = "20260812_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("departure_city", sa.String(128), nullable=True),
        sa.Column("budget_level", sa.String(16), nullable=False, server_default="balanced"),
        sa.Column("travel_pace", sa.String(16), nullable=False, server_default="balanced"),
        sa.Column("interest_tags", mysql.JSON(), nullable=False, server_default=sa.text("(JSON_ARRAY())")),
        sa.Column("traveler_type", sa.String(16), nullable=False, server_default="friends"),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("order_notifications", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("itinerary_notifications", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("community_notifications", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("profile_visibility", sa.String(16), nullable=False, server_default="collaborators"),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("budget_level IN ('economy', 'balanced', 'premium')", name="ck_user_settings_budget_level"),
        sa.CheckConstraint("travel_pace IN ('relaxed', 'balanced', 'packed')", name="ck_user_settings_travel_pace"),
        sa.CheckConstraint("traveler_type IN ('solo', 'couple', 'friends', 'family')", name="ck_user_settings_traveler_type"),
        sa.CheckConstraint("profile_visibility IN ('private', 'collaborators')", name="ck_user_settings_profile_visibility"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("user_settings")
