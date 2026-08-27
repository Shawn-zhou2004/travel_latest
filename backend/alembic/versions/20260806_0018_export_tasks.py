"""Create asynchronous private DOCX export tasks.

Revision ID: 20260806_0018
Revises: 20260806_0017
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260806_0018"
down_revision = "20260806_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.drop_constraint("ck_media_assets_mime_type", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_mime_type",
        "media_assets",
        "mime_type IN ('image/jpeg', 'image/png', 'image/webp', "
        "'application/vnd.openxmlformats-officedocument.wordprocessingml.document')",
    )
    op.create_table(
        "export_tasks",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("requester_id", sa.String(36), nullable=False),
        sa.Column("itinerary_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(16), nullable=False, server_default="docx"),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("snapshot_json", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_asset_id", sa.String(36), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", timestamp, nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("last_error_message", sa.String(500), nullable=True),
        sa.Column("trace_id", sa.String(36), nullable=True),
        sa.Column("finished_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("format = 'docx'", name="ck_export_tasks_format"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="ck_export_tasks_status"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_export_tasks_progress"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_export_tasks_attempt_count"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], name="fk_export_tasks_requester_id_users"),
        sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], ondelete="RESTRICT", name="fk_export_tasks_itinerary_id_itineraries"),
        sa.ForeignKeyConstraint(["output_asset_id"], ["media_assets.id"], ondelete="SET NULL", name="fk_export_tasks_output_asset_id_media_assets"),
        sa.PrimaryKeyConstraint("id", name="pk_export_tasks"),
        sa.UniqueConstraint("requester_id", "idempotency_key", name="uq_export_tasks_requester_key"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_export_tasks_requester_id", "export_tasks", ["requester_id"])
    op.create_index("ix_export_tasks_itinerary_id", "export_tasks", ["itinerary_id"])
    op.create_index("ix_export_tasks_status", "export_tasks", ["status"])
    op.create_index("ix_export_tasks_output_asset_id", "export_tasks", ["output_asset_id"])
    op.create_index("ix_export_tasks_trace_id", "export_tasks", ["trace_id"])


def downgrade() -> None:
    op.drop_table("export_tasks")
    op.drop_constraint("ck_media_assets_mime_type", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_mime_type",
        "media_assets",
        "mime_type IN ('image/jpeg', 'image/png', 'image/webp')",
    )
