"""Add durable refund request facts.

Revision ID: 20260807_0023
Revises: 20260807_0022
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260807_0023"
down_revision = "20260807_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)

    op.add_column("refund_records", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.add_column("refund_records", sa.Column("currency", sa.String(3), nullable=True))
    op.add_column("refund_records", sa.Column("reason", sa.String(500), nullable=True))
    op.add_column("refund_records", sa.Column("requested_by", sa.String(36), nullable=True))
    op.add_column("refund_records", sa.Column("requested_at", timestamp, nullable=True))
    op.add_column("refund_records", sa.Column("completed_at", timestamp, nullable=True))
    op.add_column("refund_records", sa.Column("failure_code", sa.String(64), nullable=True))

    # Legacy refund rows predate request facts. Payment/order ownership and stored timestamps make this backfill reproducible.
    op.execute(
        "UPDATE refund_records AS refund "
        "JOIN payment_records AS payment ON payment.id = refund.payment_id "
        "JOIN travel_orders AS travel_order ON travel_order.id = payment.order_id "
        "SET refund.idempotency_key = CONCAT('legacy:', refund.id), "
        "refund.currency = payment.currency, "
        "refund.reason = 'legacy_refund_record', "
        "refund.requested_by = travel_order.user_id, "
        "refund.requested_at = refund.created_at, "
        "refund.completed_at = CASE "
        "WHEN refund.status IN ('refunded', 'failed') THEN refund.updated_at "
        "ELSE NULL END, "
        "refund.failure_code = CASE "
        "WHEN refund.status = 'failed' THEN 'legacy_refund_failed' "
        "ELSE NULL END"
    )

    op.alter_column("refund_records", "idempotency_key", existing_type=sa.String(128), nullable=False)
    op.alter_column("refund_records", "currency", existing_type=sa.String(3), nullable=False)
    op.alter_column("refund_records", "reason", existing_type=sa.String(500), nullable=False)
    op.alter_column("refund_records", "requested_by", existing_type=sa.String(36), nullable=False)
    op.alter_column("refund_records", "requested_at", existing_type=timestamp, nullable=False)
    op.create_foreign_key("fk_refund_records_requested_by_users", "refund_records", "users", ["requested_by"], ["id"])
    op.create_index("ix_refund_records_requested_by", "refund_records", ["requested_by"])
    op.create_unique_constraint("uq_refund_records_payment_key", "refund_records", ["payment_id", "idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_refund_records_payment_key", "refund_records", type_="unique")
    op.drop_constraint("fk_refund_records_requested_by_users", "refund_records", type_="foreignkey")
    op.drop_index("ix_refund_records_requested_by", table_name="refund_records")
    op.drop_column("refund_records", "failure_code")
    op.drop_column("refund_records", "completed_at")
    op.drop_column("refund_records", "requested_at")
    op.drop_column("refund_records", "requested_by")
    op.drop_column("refund_records", "reason")
    op.drop_column("refund_records", "currency")
    op.drop_column("refund_records", "idempotency_key")
