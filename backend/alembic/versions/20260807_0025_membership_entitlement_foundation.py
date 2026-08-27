"""Create operator-managed membership and entitlement foundation.

Revision ID: 20260807_0025
Revises: 20260807_0024
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260807_0025"
down_revision = "20260807_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    op.create_table(
        "membership_plans",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("entitlement_codes", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("duration_days > 0", name="ck_membership_plans_duration_days"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_membership_plans_status"),
        sa.PrimaryKeyConstraint("id", name="pk_membership_plans"),
        sa.UniqueConstraint("code", name="uq_membership_plans_code"),
        **options,
    )
    op.create_index("ix_membership_plans_status", "membership_plans", ["status"])
    op.create_table(
        "user_memberships",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("plan_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("valid_from", timestamp, nullable=False),
        sa.Column("valid_until", timestamp, nullable=False),
        sa.Column("grant_source", sa.String(32), nullable=False, server_default="admin_grant"),
        sa.Column("granted_by", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("revoked_by", sa.String(36), nullable=True),
        sa.Column("revoked_at", timestamp, nullable=True),
        sa.Column("revoke_reason", sa.String(500), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('active', 'revoked', 'expired')", name="ck_user_memberships_status"),
        sa.CheckConstraint("grant_source = 'admin_grant'", name="ck_user_memberships_grant_source"),
        sa.CheckConstraint("valid_until > valid_from", name="ck_user_memberships_valid_window"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_memberships_user_id_users"),
        sa.ForeignKeyConstraint(["plan_id"], ["membership_plans.id"], name="fk_user_memberships_plan_id_membership_plans"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], name="fk_user_memberships_granted_by_users"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], name="fk_user_memberships_revoked_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_user_memberships"),
        sa.UniqueConstraint("granted_by", "idempotency_key", name="uq_user_memberships_granter_key"),
        **options,
    )
    op.create_index("ix_user_memberships_user_id", "user_memberships", ["user_id"])
    op.create_index("ix_user_memberships_plan_id", "user_memberships", ["plan_id"])
    op.create_index("ix_user_memberships_status", "user_memberships", ["status"])
    op.create_index("ix_user_memberships_valid_from", "user_memberships", ["valid_from"])
    op.create_index("ix_user_memberships_valid_until", "user_memberships", ["valid_until"])
    op.create_index("ix_user_memberships_granted_by", "user_memberships", ["granted_by"])
    op.create_index("ix_user_memberships_revoked_by", "user_memberships", ["revoked_by"])
    op.create_table(
        "user_entitlements",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("membership_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("entitlement_code", sa.String(64), nullable=False),
        sa.Column("valid_from", timestamp, nullable=False),
        sa.Column("valid_until", timestamp, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.CheckConstraint("valid_until > valid_from", name="ck_user_entitlements_valid_window"),
        sa.ForeignKeyConstraint(["membership_id"], ["user_memberships.id"], ondelete="CASCADE", name="fk_user_entitlements_membership_id_user_memberships"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_entitlements_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_user_entitlements"),
        sa.UniqueConstraint("membership_id", "entitlement_code", name="uq_user_entitlements_membership_code"),
        **options,
    )
    op.create_index("ix_user_entitlements_membership_id", "user_entitlements", ["membership_id"])
    op.create_index("ix_user_entitlements_user_id", "user_entitlements", ["user_id"])
    op.create_index("ix_user_entitlements_entitlement_code", "user_entitlements", ["entitlement_code"])
    op.create_index("ix_user_entitlements_valid_from", "user_entitlements", ["valid_from"])
    op.create_index("ix_user_entitlements_valid_until", "user_entitlements", ["valid_until"])


def downgrade() -> None:
    op.drop_table("user_entitlements")
    op.drop_table("user_memberships")
    op.drop_table("membership_plans")
