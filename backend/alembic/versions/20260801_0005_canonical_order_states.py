"""Align commerce states with the canonical order contract.

Revision ID: 20260801_0005
Revises: 20260801_0004
"""

from alembic import op
import sqlalchemy as sa


revision = "20260801_0005"
down_revision = "20260801_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("travel_orders", sa.Column("failure_code", sa.String(length=64), nullable=True))
    op.drop_constraint("ck_travel_orders_status", "travel_orders", type_="check")
    op.drop_constraint("ck_travel_orders_payment_status", "travel_orders", type_="check")
    op.drop_constraint("ck_travel_orders_fulfillment_status", "travel_orders", type_="check")
    op.drop_constraint("ck_payment_records_status", "payment_records", type_="check")

    op.execute("""
        UPDATE travel_orders
        SET status = CASE status
            WHEN 'created' THEN 'PENDING_CONFIRMATION'
            WHEN 'payment_pending' THEN 'PAYING'
            WHEN 'paid_pending_fulfillment' THEN 'PAID_PENDING_FULFILLMENT'
            WHEN 'fulfillment_confirmed' THEN 'CONFIRMED'
            WHEN 'cancelled' THEN 'CLOSED'
            WHEN 'refunded' THEN 'REFUNDED'
            ELSE status END,
            payment_status = CASE payment_status
                WHEN 'unpaid' THEN 'pending'
                WHEN 'unavailable' THEN 'failed'
                ELSE payment_status END,
            fulfillment_status = CASE fulfillment_status
                WHEN 'not_started' THEN 'pending_confirmation'
                WHEN 'cancelled' THEN 'not_supported'
                ELSE fulfillment_status END
    """)
    op.execute("""
        UPDATE payment_records
        SET status = CASE status
            WHEN 'created' THEN 'pending'
            WHEN 'unavailable' THEN 'failed'
            ELSE status END
    """)

    op.create_check_constraint(
        "ck_travel_orders_status",
        "travel_orders",
        "status IN ('PENDING_CONFIRMATION', 'PAYING', 'PAID_PENDING_FULFILLMENT', 'CONFIRMED', 'FAILED', 'REFUNDING', 'REFUNDED', 'CLOSED')",
    )
    op.create_check_constraint(
        "ck_travel_orders_payment_status",
        "travel_orders",
        "payment_status IN ('pending', 'paying', 'paid', 'failed', 'refunding', 'refunded')",
    )
    op.create_check_constraint(
        "ck_travel_orders_fulfillment_status",
        "travel_orders",
        "fulfillment_status IN ('pending_confirmation', 'confirming', 'confirmed', 'failed', 'not_supported')",
    )
    op.create_check_constraint(
        "ck_payment_records_status",
        "payment_records",
        "status IN ('pending', 'paying', 'paid', 'failed', 'refunding', 'refunded')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_travel_orders_status", "travel_orders", type_="check")
    op.drop_constraint("ck_travel_orders_payment_status", "travel_orders", type_="check")
    op.drop_constraint("ck_travel_orders_fulfillment_status", "travel_orders", type_="check")
    op.drop_constraint("ck_payment_records_status", "payment_records", type_="check")

    op.execute("""
        UPDATE travel_orders
        SET status = CASE status
            WHEN 'PENDING_CONFIRMATION' THEN 'created'
            WHEN 'PAYING' THEN 'payment_pending'
            WHEN 'PAID_PENDING_FULFILLMENT' THEN 'paid_pending_fulfillment'
            WHEN 'CONFIRMED' THEN 'fulfillment_confirmed'
            WHEN 'FAILED' THEN 'cancelled'
            WHEN 'REFUNDING' THEN 'paid_pending_fulfillment'
            WHEN 'REFUNDED' THEN 'refunded'
            WHEN 'CLOSED' THEN 'cancelled'
            ELSE status END,
            payment_status = CASE payment_status
                WHEN 'paying' THEN 'pending'
                WHEN 'refunding' THEN 'pending'
                WHEN 'failed' THEN 'unavailable'
                ELSE payment_status END,
            fulfillment_status = CASE fulfillment_status
                WHEN 'confirming' THEN 'pending_confirmation'
                WHEN 'not_supported' THEN 'cancelled'
                ELSE fulfillment_status END
    """)
    op.execute("""
        UPDATE payment_records
        SET status = CASE status
            WHEN 'paying' THEN 'pending'
            WHEN 'refunding' THEN 'pending'
            WHEN 'failed' THEN 'unavailable'
            ELSE status END
    """)

    op.create_check_constraint(
        "ck_travel_orders_status",
        "travel_orders",
        "status IN ('created', 'payment_pending', 'paid_pending_fulfillment', 'fulfillment_confirmed', 'cancelled', 'refunded')",
    )
    op.create_check_constraint(
        "ck_travel_orders_payment_status",
        "travel_orders",
        "payment_status IN ('unpaid', 'pending', 'paid', 'refunded', 'unavailable')",
    )
    op.create_check_constraint(
        "ck_travel_orders_fulfillment_status",
        "travel_orders",
        "fulfillment_status IN ('not_started', 'pending_confirmation', 'confirmed', 'failed', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_payment_records_status",
        "payment_records",
        "status IN ('created', 'pending', 'paid', 'failed', 'unavailable', 'refunded')",
    )
    op.drop_column("travel_orders", "failure_code")
