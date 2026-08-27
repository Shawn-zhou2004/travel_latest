"""Add membership QR payment attempts.

Revision ID: 20260813_0043
Revises: 20260813_0042
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260813_0043"
down_revision = "20260813_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    op.create_table(
        "membership_payment_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("membership_purchase_id", sa.String(length=36), nullable=False),
        sa.Column("payment_no", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("qr_code", sa.String(length=2048), nullable=True),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=128), nullable=True),
        sa.Column("paid_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('pending', 'paying', 'paid', 'expired', 'closed', 'failed')", name="ck_membership_payment_attempts_status"),
        sa.ForeignKeyConstraint(["membership_purchase_id"], ["membership_purchases.id"], name="fk_membership_payment_attempts_purchase"),
        sa.PrimaryKeyConstraint("id", name="pk_membership_payment_attempts"),
        sa.UniqueConstraint("payment_no", name="uq_membership_payment_attempts_payment_no"),
        sa.UniqueConstraint("provider_transaction_id", name="uq_membership_payment_attempts_provider_transaction_id"),
        **options,
    )
    op.create_index("ix_membership_payment_attempts_membership_purchase_id", "membership_payment_attempts", ["membership_purchase_id"])
    op.create_index("ix_membership_payment_attempts_status", "membership_payment_attempts", ["status"])
    op.create_index("ix_membership_payment_attempts_expires_at", "membership_payment_attempts", ["expires_at"])
    op.add_column("membership_purchases", sa.Column("current_payment_attempt_id", sa.String(length=36), nullable=True))
    op.create_index("ix_membership_purchases_current_payment_attempt_id", "membership_purchases", ["current_payment_attempt_id"])
    op.create_foreign_key("fk_membership_purchases_current_payment_attempt", "membership_purchases", "membership_payment_attempts", ["current_payment_attempt_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_membership_purchases_current_payment_attempt", "membership_purchases", type_="foreignkey")
    op.drop_index("ix_membership_purchases_current_payment_attempt_id", table_name="membership_purchases")
    op.drop_column("membership_purchases", "current_payment_attempt_id")
    op.drop_table("membership_payment_attempts")
