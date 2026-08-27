"""Add membership payment callback audit and purchase authorization source.

Revision ID: 20260813_0042
Revises: 20260813_0041
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260813_0042"
down_revision = "20260813_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    op.drop_constraint("ck_user_memberships_grant_source", "user_memberships", type_="check")
    op.create_check_constraint(
        "ck_user_memberships_grant_source",
        "user_memberships",
        "grant_source IN ('admin_grant', 'membership_purchase')",
    )
    op.add_column("membership_purchases", sa.Column("provider_transaction_id", sa.String(length=128), nullable=True))
    op.create_unique_constraint("uq_membership_purchases_provider_transaction_id", "membership_purchases", ["provider_transaction_id"])
    op.create_table(
        "membership_payment_callback_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=128), nullable=True),
        sa.Column("membership_purchase_id", sa.String(length=36), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("received_at", timestamp, nullable=False),
        sa.Column("verification_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("verification_error", sa.String(length=255), nullable=True),
        sa.Column("verified_at", timestamp, nullable=True),
        sa.Column("processing_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("processing_error", sa.String(length=255), nullable=True),
        sa.Column("processed_at", timestamp, nullable=True),
        sa.CheckConstraint("verification_status IN ('pending', 'verified', 'rejected')", name="ck_membership_payment_callbacks_verification_status"),
        sa.CheckConstraint("processing_status IN ('pending', 'processed', 'failed')", name="ck_membership_payment_callbacks_processing_status"),
        sa.ForeignKeyConstraint(["membership_purchase_id"], ["membership_purchases.id"], name="fk_membership_payment_callbacks_purchase"),
        sa.PrimaryKeyConstraint("id", name="pk_membership_payment_callback_events"),
        sa.UniqueConstraint("provider", "provider_transaction_id", name="uq_membership_payment_callbacks_provider_tx"),
        **options,
    )
    op.create_index("ix_membership_payment_callback_events_membership_purchase_id", "membership_payment_callback_events", ["membership_purchase_id"])


def downgrade() -> None:
    op.drop_table("membership_payment_callback_events")
    op.drop_constraint("uq_membership_purchases_provider_transaction_id", "membership_purchases", type_="unique")
    op.drop_column("membership_purchases", "provider_transaction_id")
    op.drop_constraint("ck_user_memberships_grant_source", "user_memberships", type_="check")
    op.create_check_constraint("ck_user_memberships_grant_source", "user_memberships", "grant_source = 'admin_grant'")
