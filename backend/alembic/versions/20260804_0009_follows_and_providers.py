"""Create follows and provider experience tables.

Revision ID: 20260804_0009
Revises: 20260804_0008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260804_0009"
down_revision = "20260804_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "follows",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("follower_id", sa.String(36), nullable=False),
        sa.Column("followee_id", sa.String(36), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("follower_id <> followee_id", name="ck_follows_not_self"),
        sa.ForeignKeyConstraint(["follower_id"], ["users.id"], ondelete="CASCADE", name="fk_follows_follower_id_users"),
        sa.ForeignKeyConstraint(["followee_id"], ["users.id"], ondelete="CASCADE", name="fk_follows_followee_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_follows"),
        sa.UniqueConstraint("follower_id", "followee_id", name="uq_follows_follower_followee"),
        **options,
    )
    op.create_index("ix_follows_follower_id", "follows", ["follower_id"])
    op.create_index("ix_follows_followee_id", "follows", ["followee_id"])
    op.create_table(
        "providers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("applicant_id", sa.String(36), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("legal_name", sa.String(160), nullable=False),
        sa.Column("contact", sa.String(160), nullable=False),
        sa.Column("qualification_asset_ids", mysql.JSON(), nullable=False),
        sa.Column("claimed_poi_ids", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_review"),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('pending_review', 'approved', 'rejected')", name="ck_providers_status"),
        sa.ForeignKeyConstraint(["applicant_id"], ["users.id"], name="fk_providers_applicant_id_users"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_providers_reviewed_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_providers"),
        **options,
    )
    op.create_index("ix_providers_applicant_id", "providers", ["applicant_id"])
    op.create_index("ix_providers_reviewed_by", "providers", ["reviewed_by"])
    op.create_index("ix_providers_status", "providers", ["status"])
    op.create_table(
        "provider_reviews",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=False),
        sa.Column("result_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE", name="fk_provider_reviews_provider_id_providers"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name="fk_provider_reviews_actor_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_provider_reviews"),
        **options,
    )
    op.create_index("ix_provider_reviews_provider_id", "provider_reviews", ["provider_id"])
    op.create_index("ix_provider_reviews_actor_id", "provider_reviews", ["actor_id"])
    op.create_table(
        "experience_services",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("poi_id", sa.String(128), nullable=False),
        sa.Column("poi_name", sa.String(160), nullable=False),
        sa.Column("poi_address", sa.String(255), nullable=False),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cancellation_policy", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_experience_services_status"),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], name="fk_experience_services_provider_id_providers"),
        sa.PrimaryKeyConstraint("id", name="pk_experience_services"),
        **options,
    )
    op.create_index("ix_experience_services_provider_id", "experience_services", ["provider_id"])
    op.create_index("ix_experience_services_status", "experience_services", ["status"])
    op.create_table(
        "experience_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("experience_id", sa.String(36), nullable=False),
        sa.Column("starts_at", timestamp, nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("reserved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("capacity > 0", name="ck_experience_sessions_capacity"),
        sa.CheckConstraint("reserved_count >= 0 AND reserved_count <= capacity", name="ck_experience_sessions_reserved_count"),
        sa.CheckConstraint("status IN ('scheduled', 'cancelled', 'completed')", name="ck_experience_sessions_status"),
        sa.ForeignKeyConstraint(["experience_id"], ["experience_services.id"], ondelete="CASCADE", name="fk_experience_sessions_experience_id_experience_services"),
        sa.PrimaryKeyConstraint("id", name="pk_experience_sessions"),
        **options,
    )
    op.create_index("ix_experience_sessions_experience_id", "experience_sessions", ["experience_id"])
    op.create_index("ix_experience_sessions_starts_at", "experience_sessions", ["starts_at"])
    op.create_table(
        "experience_bookings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("experience_session_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("traveler_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="reserved"),
        sa.Column("verification_code", sa.String(24), nullable=False),
        sa.Column("verified_at", timestamp, nullable=True),
        sa.CheckConstraint("traveler_count > 0", name="ck_experience_bookings_travelers"),
        sa.CheckConstraint("status IN ('reserved', 'verified', 'cancelled')", name="ck_experience_bookings_status"),
        sa.ForeignKeyConstraint(["experience_session_id"], ["experience_sessions.id"], name="fk_experience_bookings_session_id_experience_sessions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_experience_bookings_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_experience_bookings"),
        sa.UniqueConstraint("experience_session_id", "user_id", name="uq_experience_bookings_session_user"),
        sa.UniqueConstraint("verification_code", name="uq_experience_bookings_verification_code"),
        **options,
    )
    op.create_index("ix_experience_bookings_session_id", "experience_bookings", ["experience_session_id"])
    op.create_index("ix_experience_bookings_user_id", "experience_bookings", ["user_id"])
    op.create_index("ix_experience_bookings_status", "experience_bookings", ["status"])
    op.create_table(
        "experience_reviews",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("booking_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_experience_reviews_rating"),
        sa.ForeignKeyConstraint(["booking_id"], ["experience_bookings.id"], name="fk_experience_reviews_booking_id_experience_bookings"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_experience_reviews_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_experience_reviews"),
        sa.UniqueConstraint("booking_id", name="uq_experience_reviews_booking"),
        **options,
    )
    op.create_index("ix_experience_reviews_booking_id", "experience_reviews", ["booking_id"])
    op.create_index("ix_experience_reviews_user_id", "experience_reviews", ["user_id"])


def downgrade() -> None:
    op.drop_table("experience_reviews")
    op.drop_table("experience_bookings")
    op.drop_table("experience_sessions")
    op.drop_table("experience_services")
    op.drop_table("provider_reviews")
    op.drop_table("providers")
    op.drop_table("follows")
