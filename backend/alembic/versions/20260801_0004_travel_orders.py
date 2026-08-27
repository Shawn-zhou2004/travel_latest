"""Create travel commerce order tables.

Revision ID: 20260801_0004
Revises: 20260801_0003
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260801_0004"
down_revision = "20260801_0003"
branch_labels = None
depends_on = None


def _options() -> dict[str, str]:
    return {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    money = sa.Numeric(12, 2)
    op.create_table("travel_search_jobs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("search_type", sa.String(16), nullable=False), sa.Column("query_snapshot", mysql.JSON(), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("source", sa.String(64), nullable=False), sa.Column("unavailable_code", sa.String(64)), sa.Column("retrieved_at", timestamp, nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("search_type IN ('flight', 'hotel', 'ride')", name="ck_travel_search_jobs_type"), sa.CheckConstraint("status IN ('pending', 'completed', 'empty', 'failed')", name="ck_travel_search_jobs_status"), sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_travel_search_jobs_user_id_users"), sa.UniqueConstraint("user_id", "idempotency_key", name="uq_travel_search_jobs_user_key"), **_options())
    op.create_index("ix_travel_search_jobs_user_id", "travel_search_jobs", ["user_id"])
    op.create_table("travel_offers", sa.Column("id", sa.String(36), primary_key=True), sa.Column("search_job_id", sa.String(36), nullable=False), sa.Column("source", sa.String(64), nullable=False), sa.Column("external_offer_id", sa.String(128), nullable=False), sa.Column("title", sa.String(255), nullable=False), sa.Column("amount", money, nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("availability", sa.String(16), nullable=False), sa.Column("valid_until", timestamp, nullable=False), sa.Column("retrieved_at", timestamp, nullable=False), sa.Column("change_rules", mysql.JSON(), nullable=False), sa.Column("snapshot", mysql.JSON(), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("availability IN ('available', 'unavailable')", name="ck_travel_offers_availability"), sa.ForeignKeyConstraint(["search_job_id"], ["travel_search_jobs.id"], name="fk_travel_offers_search_job_id_jobs"), **_options())
    op.create_index("ix_travel_offers_search_job_id", "travel_offers", ["search_job_id"])
    op.create_index("ix_travel_offers_valid_until", "travel_offers", ["valid_until"])
    op.create_table("travel_orders", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), nullable=False), sa.Column("offer_id", sa.String(36), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("order_no", sa.String(40), nullable=False), sa.Column("amount", money, nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("offer_snapshot", mysql.JSON(), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("payment_status", sa.String(16), nullable=False), sa.Column("fulfillment_status", sa.String(24), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("status IN ('created', 'payment_pending', 'paid_pending_fulfillment', 'fulfillment_confirmed', 'cancelled', 'refunded')", name="ck_travel_orders_status"), sa.CheckConstraint("payment_status IN ('unpaid', 'pending', 'paid', 'refunded', 'unavailable')", name="ck_travel_orders_payment_status"), sa.CheckConstraint("fulfillment_status IN ('not_started', 'pending_confirmation', 'confirmed', 'failed', 'cancelled')", name="ck_travel_orders_fulfillment_status"), sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_travel_orders_user_id_users"), sa.ForeignKeyConstraint(["offer_id"], ["travel_offers.id"], name="fk_travel_orders_offer_id_offers"), sa.UniqueConstraint("order_no", name="uq_travel_orders_order_no"), sa.UniqueConstraint("user_id", "idempotency_key", name="uq_travel_orders_user_key"), **_options())
    op.create_index("ix_travel_orders_user_id", "travel_orders", ["user_id"])
    op.create_index("ix_travel_orders_offer_id", "travel_orders", ["offer_id"])
    op.create_table("payment_records", sa.Column("id", sa.String(36), primary_key=True), sa.Column("order_id", sa.String(36), nullable=False), sa.Column("payment_no", sa.String(40), nullable=False), sa.Column("provider", sa.String(32), nullable=False), sa.Column("amount", money, nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("provider_transaction_id", sa.String(128)), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("status IN ('created', 'pending', 'paid', 'failed', 'unavailable', 'refunded')", name="ck_payment_records_status"), sa.ForeignKeyConstraint(["order_id"], ["travel_orders.id"], name="fk_payment_records_order_id_orders"), sa.UniqueConstraint("payment_no", name="uq_payment_records_payment_no"), sa.UniqueConstraint("provider_transaction_id", name="uq_payment_records_provider_tx"), **_options())
    op.create_index("ix_payment_records_order_id", "payment_records", ["order_id"])
    op.create_table("payment_callback_events", sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider", sa.String(32), nullable=False), sa.Column("provider_transaction_id", sa.String(128), nullable=False), sa.Column("payment_id", sa.String(36)), sa.Column("raw_payload", mysql.JSON(), nullable=False), sa.Column("received_at", timestamp, nullable=False), sa.ForeignKeyConstraint(["payment_id"], ["payment_records.id"], name="fk_payment_callback_events_payment_id_payments"), sa.UniqueConstraint("provider", "provider_transaction_id", name="uq_payment_callback_provider_tx"), **_options())
    op.create_index("ix_payment_callback_events_payment_id", "payment_callback_events", ["payment_id"])
    op.create_table("refund_records", sa.Column("id", sa.String(36), primary_key=True), sa.Column("payment_id", sa.String(36), nullable=False), sa.Column("refund_no", sa.String(40), nullable=False), sa.Column("amount", money, nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("provider_refund_id", sa.String(128)), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("status IN ('requested', 'processing', 'refunded', 'failed')", name="ck_refund_records_status"), sa.ForeignKeyConstraint(["payment_id"], ["payment_records.id"], name="fk_refund_records_payment_id_payments"), sa.UniqueConstraint("refund_no", name="uq_refund_records_refund_no"), sa.UniqueConstraint("provider_refund_id", name="uq_refund_records_provider_refund"), **_options())
    op.create_index("ix_refund_records_payment_id", "refund_records", ["payment_id"])


def downgrade() -> None:
    op.drop_table("refund_records")
    op.drop_table("payment_callback_events")
    op.drop_table("payment_records")
    op.drop_table("travel_orders")
    op.drop_table("travel_offers")
    op.drop_table("travel_search_jobs")
