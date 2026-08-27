"""Add membership purchase and AI quota persistence.

Revision ID: 20260813_0041
Revises: 20260813_0040
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260813_0041"
down_revision = "20260813_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    op.add_column(
        "membership_plans",
        sa.Column("price_amount", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )
    op.add_column(
        "membership_plans",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="CNY"),
    )
    op.add_column(
        "membership_plans",
        sa.Column("generation_quota", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "membership_plans",
        sa.Column("assistant_quota", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "membership_plans",
        sa.Column("purchasable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "membership_purchases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("membership_plan_id", sa.String(length=36), nullable=False),
        sa.Column("plan_name_snapshot", sa.String(length=160), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("generation_quota", sa.Integer(), nullable=False),
        sa.Column("assistant_quota", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_payment"),
        sa.Column("payment_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("authorization_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payment_no", sa.String(length=40), nullable=True),
        sa.Column("paid_at", timestamp, nullable=True),
        sa.Column("authorized_at", timestamp, nullable=True),
        sa.Column("valid_from", timestamp, nullable=True),
        sa.Column("valid_until", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('pending_payment', 'paid', 'closed')", name="ck_membership_purchases_status"),
        sa.CheckConstraint("payment_status IN ('pending', 'paying', 'paid', 'failed')", name="ck_membership_purchases_payment_status"),
        sa.CheckConstraint("authorization_status IN ('pending', 'authorized', 'failed')", name="ck_membership_purchases_authorization_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_membership_purchases_user_id_users"),
        sa.ForeignKeyConstraint(["membership_plan_id"], ["membership_plans.id"], name="fk_membership_purchases_membership_plan_id_membership_plans"),
        sa.PrimaryKeyConstraint("id", name="pk_membership_purchases"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_membership_purchases_user_idempotency"),
        sa.UniqueConstraint("payment_no", name="uq_membership_purchases_payment_no"),
        **options,
    )
    op.create_index("ix_membership_purchases_user_id", "membership_purchases", ["user_id"])
    op.create_index("ix_membership_purchases_membership_plan_id", "membership_purchases", ["membership_plan_id"])
    op.create_index("ix_membership_purchases_status", "membership_purchases", ["status"])
    op.create_index("ix_membership_purchases_payment_status", "membership_purchases", ["payment_status"])
    op.create_index("ix_membership_purchases_authorization_status", "membership_purchases", ["authorization_status"])

    op.create_table(
        "ai_quota_periods",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("membership_purchase_id", sa.String(length=36), nullable=True),
        sa.Column("period_start", timestamp, nullable=False),
        sa.Column("period_end", timestamp, nullable=False),
        sa.Column("generation_limit", sa.Integer(), nullable=False),
        sa.Column("generation_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assistant_limit", sa.Integer(), nullable=False),
        sa.Column("assistant_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("source_type IN ('free', 'membership_purchase')", name="ck_ai_quota_periods_source_type"),
        sa.CheckConstraint("period_end > period_start", name="ck_ai_quota_periods_window"),
        sa.CheckConstraint("generation_used >= 0 AND generation_used <= generation_limit", name="ck_ai_quota_generation_bounds"),
        sa.CheckConstraint("assistant_used >= 0 AND assistant_used <= assistant_limit", name="ck_ai_quota_assistant_bounds"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_ai_quota_periods_user_id_users"),
        sa.ForeignKeyConstraint(["membership_purchase_id"], ["membership_purchases.id"], name="fk_ai_quota_periods_membership_purchase_id_membership_purchases"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_quota_periods"),
        sa.UniqueConstraint("membership_purchase_id", name="uq_ai_quota_periods_purchase"),
        **options,
    )
    op.create_index("ix_ai_quota_periods_user_id", "ai_quota_periods", ["user_id"])
    op.create_index("ix_ai_quota_periods_source_type", "ai_quota_periods", ["source_type"])
    op.create_index("ix_ai_quota_periods_membership_purchase_id", "ai_quota_periods", ["membership_purchase_id"])
    op.create_index("ix_ai_quota_periods_period_start", "ai_quota_periods", ["period_start"])
    op.create_index("ix_ai_quota_periods_period_end", "ai_quota_periods", ["period_end"])


def downgrade() -> None:
    op.drop_table("ai_quota_periods")
    op.drop_table("membership_purchases")
    op.drop_column("membership_plans", "purchasable")
    op.drop_column("membership_plans", "assistant_quota")
    op.drop_column("membership_plans", "generation_quota")
    op.drop_column("membership_plans", "currency")
    op.drop_column("membership_plans", "price_amount")
