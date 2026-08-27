"""Repair the refund idempotency uniqueness fact.

Revision ID: 20260807_0024
Revises: 20260807_0023
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0024"
down_revision = "20260807_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    constraints = {item["name"] for item in inspector.get_unique_constraints("refund_records")}
    if "uq_refund_records_payment_key" not in constraints:
        op.create_unique_constraint(
            "uq_refund_records_payment_key",
            "refund_records",
            ["payment_id", "idempotency_key"],
        )


def downgrade() -> None:
    # Keep the repaired constraint for 0023's downgrade, which owns its removal.
    pass
