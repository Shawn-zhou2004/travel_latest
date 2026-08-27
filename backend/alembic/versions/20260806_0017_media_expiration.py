"""Add durable expiration state for pending media uploads.

Revision ID: 20260806_0017
Revises: 20260806_0016
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260806_0017"
down_revision = "20260806_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_assets",
        sa.Column("upload_expires_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    # Pending rows created before this deployment receive the same 15-minute lease.
    op.execute(
        "UPDATE media_assets "
        "SET upload_expires_at = DATE_ADD(created_at, INTERVAL 900 SECOND) "
        "WHERE status = 'pending'"
    )
    op.drop_constraint("ck_media_assets_status", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_status",
        "media_assets",
        "status IN ('pending', 'completed', 'expired') "
        "AND (status != 'pending' OR upload_expires_at IS NOT NULL)",
    )
    op.create_index(
        "ix_media_assets_status_upload_expires_at",
        "media_assets",
        ["status", "upload_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_assets_status_upload_expires_at", table_name="media_assets")
    # The prior constraint has no expired state; retain the asset fact as pending.
    op.execute("UPDATE media_assets SET status = 'pending' WHERE status = 'expired'")
    op.drop_constraint("ck_media_assets_status", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_status",
        "media_assets",
        "status IN ('pending', 'completed')",
    )
    op.drop_column("media_assets", "upload_expires_at")
