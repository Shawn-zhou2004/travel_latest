"""Index pending Outbox scans.

Revision ID: 20260811_0035
Revises: 20260810_0034
Create Date: 2026-08-11
"""

from alembic import op
from sqlalchemy import inspect


revision = "20260811_0035"
down_revision = "20260810_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("outbox_events")}
    if "ix_outbox_events_pending" not in indexes:
        op.create_index(
            "ix_outbox_events_pending",
            "outbox_events",
            ["published_at", "created_at", "event_id"],
        )


def downgrade() -> None:
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("outbox_events")}
    if "ix_outbox_events_pending" in indexes:
        op.drop_index("ix_outbox_events_pending", table_name="outbox_events")
