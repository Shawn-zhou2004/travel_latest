"""Create itinerary checklist and budget tables.

Revision ID: 20260804_0006
Revises: 20260801_0005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260804_0006"
down_revision = "20260801_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "checklist_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("itinerary_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], ondelete="CASCADE", name="fk_checklist_items_itinerary_id_itineraries"),
        **options,
    )
    op.create_index("ix_checklist_items_itinerary_id", "checklist_items", ["itinerary_id"])
    op.create_table(
        "budget_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("itinerary_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_budget_items_amount"),
        sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], ondelete="CASCADE", name="fk_budget_items_itinerary_id_itineraries"),
        **options,
    )
    op.create_index("ix_budget_items_itinerary_id", "budget_items", ["itinerary_id"])


def downgrade() -> None:
    op.drop_table("budget_items")
    op.drop_table("checklist_items")
