"""Create private media asset facts.

Revision ID: 20260806_0016
Revises: 20260806_0015
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260806_0016"
down_revision = "20260806_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "media_assets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("etag", sa.String(128), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('pending', 'completed')", name="ck_media_assets_status"),
        sa.CheckConstraint("mime_type IN ('image/jpeg', 'image/png', 'image/webp')", name="ck_media_assets_mime_type"),
        sa.CheckConstraint("size_bytes > 0", name="ck_media_assets_size_bytes"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_media_assets_owner_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_media_assets"),
        sa.UniqueConstraint("object_key", name="uq_media_assets_object_key"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_media_assets_owner_id", "media_assets", ["owner_id"])


def downgrade() -> None:
    op.drop_table("media_assets")
