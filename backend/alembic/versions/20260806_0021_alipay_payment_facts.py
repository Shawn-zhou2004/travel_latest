"""Add durable Alipay payment and callback facts.

Revision ID: 20260806_0021
Revises: 20260806_0020
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260806_0021"
down_revision = "20260806_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)

    op.add_column("payment_records", sa.Column("idempotency_key", sa.String(128), nullable=True))
    # Each pre-idempotency payment remains independently addressable after the new key is required.
    op.execute("UPDATE payment_records SET idempotency_key = CONCAT('legacy:', id) WHERE idempotency_key IS NULL")
    op.alter_column("payment_records", "idempotency_key", existing_type=sa.String(128), nullable=False)
    op.add_column("payment_records", sa.Column("paid_at", timestamp, nullable=True))
    op.create_unique_constraint("uq_payment_records_order_key", "payment_records", ["order_id", "idempotency_key"])

    op.drop_constraint("uq_payment_callback_provider_tx", "payment_callback_events", type_="unique")
    op.alter_column(
        "payment_callback_events",
        "provider_transaction_id",
        existing_type=sa.String(128),
        nullable=True,
    )
    op.create_unique_constraint(
        "uq_payment_callback_provider_tx",
        "payment_callback_events",
        ["provider", "provider_transaction_id"],
    )
    op.add_column(
        "payment_callback_events",
        sa.Column("verification_status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column("payment_callback_events", sa.Column("verification_error", sa.String(255), nullable=True))
    op.add_column("payment_callback_events", sa.Column("verified_at", timestamp, nullable=True))
    op.add_column(
        "payment_callback_events",
        sa.Column("processing_status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column("payment_callback_events", sa.Column("processing_error", sa.String(255), nullable=True))
    op.add_column("payment_callback_events", sa.Column("processed_at", timestamp, nullable=True))
    op.create_check_constraint(
        "ck_payment_callback_events_verification_status",
        "payment_callback_events",
        "verification_status IN ('pending', 'verified', 'rejected')",
    )
    op.create_check_constraint(
        "ck_payment_callback_events_processing_status",
        "payment_callback_events",
        "processing_status IN ('pending', 'processed', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payment_callback_events_processing_status", "payment_callback_events", type_="check")
    op.drop_constraint("ck_payment_callback_events_verification_status", "payment_callback_events", type_="check")
    op.drop_column("payment_callback_events", "processed_at")
    op.drop_column("payment_callback_events", "processing_error")
    op.drop_column("payment_callback_events", "processing_status")
    op.drop_column("payment_callback_events", "verified_at")
    op.drop_column("payment_callback_events", "verification_error")
    op.drop_column("payment_callback_events", "verification_status")
    op.drop_constraint("uq_payment_callback_provider_tx", "payment_callback_events", type_="unique")
    # The previous schema forbids NULL IDs; preserve rejected malformed facts with a stable synthetic legacy ID.
    op.execute(
        "UPDATE payment_callback_events "
        "SET provider_transaction_id = CONCAT('rejected:', id) "
        "WHERE provider_transaction_id IS NULL"
    )
    op.alter_column(
        "payment_callback_events",
        "provider_transaction_id",
        existing_type=sa.String(128),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_payment_callback_provider_tx",
        "payment_callback_events",
        ["provider", "provider_transaction_id"],
    )

    op.drop_constraint("uq_payment_records_order_key", "payment_records", type_="unique")
    op.drop_column("payment_records", "paid_at")
    op.drop_column("payment_records", "idempotency_key")
