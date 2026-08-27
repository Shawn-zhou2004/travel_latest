"""Add durable order fulfillment attempts.

Revision ID: 20260807_0022
Revises: 20260806_0021
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260807_0022"
down_revision = "20260806_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "fulfillment_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("external_confirmation_id", sa.String(128), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("redacted_result", mysql.JSON(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("queued_at", timestamp, nullable=False),
        sa.Column("last_attempt_at", timestamp, nullable=True),
        sa.Column("started_at", timestamp, nullable=True),
        sa.Column("completed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_fulfillment_attempts_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_fulfillment_attempts_attempt_count"),
        sa.ForeignKeyConstraint(["order_id"], ["travel_orders.id"], name="fk_fulfillment_attempts_order_id_orders"),
        sa.UniqueConstraint("order_id", name="uq_fulfillment_attempts_order"),
        sa.UniqueConstraint("idempotency_key", name="uq_fulfillment_attempts_idempotency_key"),
        sa.UniqueConstraint("external_confirmation_id", name="uq_fulfillment_attempts_external_confirmation_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("fulfillment_attempts")
