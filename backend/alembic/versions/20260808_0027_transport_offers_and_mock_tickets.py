"""Add train search support and mock transport ticket facts.

Revision ID: 20260808_0027
Revises: 20260808_0026
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260808_0027"
down_revision = "20260808_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    op.drop_constraint("ck_travel_search_jobs_type", "travel_search_jobs", type_="check")
    op.create_check_constraint("ck_travel_search_jobs_type", "travel_search_jobs", "search_type IN ('train', 'flight', 'hotel', 'ride')")
    op.drop_constraint("ck_travel_orders_status", "travel_orders", type_="check")
    op.create_check_constraint("ck_travel_orders_status", "travel_orders", "status IN ('PENDING_CONFIRMATION', 'PAYING', 'PAID_PENDING_FULFILLMENT', 'CONFIRMED', 'FAILED', 'TICKET_FAILED_AWAITING_REFUND', 'REFUNDING', 'REFUNDED', 'CLOSED')")
    op.create_table(
        "mock_transport_tickets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("transport_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mock_ticket_no", sa.String(64), nullable=True),
        sa.Column("seat_assignments", mysql.JSON(), nullable=False),
        sa.Column("passenger_facts", mysql.JSON(), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("transport_type IN ('train', 'flight')", name="ck_mock_transport_tickets_type"),
        sa.CheckConstraint("status IN ('pending', 'issued', 'failed')", name="ck_mock_transport_tickets_status"),
        sa.ForeignKeyConstraint(["order_id"], ["travel_orders.id"], name="fk_mock_transport_tickets_order_id_orders"),
        sa.PrimaryKeyConstraint("id", name="pk_mock_transport_tickets"),
        sa.UniqueConstraint("order_id", name="uq_mock_transport_tickets_order"),
        sa.UniqueConstraint("mock_ticket_no", name="uq_mock_transport_tickets_ticket_no"),
        **options,
    )
    op.create_index("ix_mock_transport_tickets_order_id", "mock_transport_tickets", ["order_id"])


def downgrade() -> None:
    op.drop_table("mock_transport_tickets")
    op.execute(
        "UPDATE travel_orders SET status = 'FAILED' "
        "WHERE status = 'TICKET_FAILED_AWAITING_REFUND'"
    )
    op.drop_constraint("ck_travel_orders_status", "travel_orders", type_="check")
    op.create_check_constraint("ck_travel_orders_status", "travel_orders", "status IN ('PENDING_CONFIRMATION', 'PAYING', 'PAID_PENDING_FULFILLMENT', 'CONFIRMED', 'FAILED', 'REFUNDING', 'REFUNDED', 'CLOSED')")
    # The prior schema has no train type; retain search-job records as flight on rollback.
    op.execute("UPDATE travel_search_jobs SET search_type = 'flight' WHERE search_type = 'train'")
    op.drop_constraint("ck_travel_search_jobs_type", "travel_search_jobs", type_="check")
    op.create_check_constraint("ck_travel_search_jobs_type", "travel_search_jobs", "search_type IN ('flight', 'hotel', 'ride')")
