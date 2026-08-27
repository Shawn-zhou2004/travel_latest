"""Add persistent companion group profile fields.

Revision ID: 20260813_0040
Revises: 20260812_0039
"""

from alembic import op
import sqlalchemy as sa


revision = "20260813_0040"
down_revision = "20260812_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("avatar_asset_id", sa.String(length=36), nullable=True))
    op.create_index("ix_conversations_avatar_asset_id", "conversations", ["avatar_asset_id"])
    op.create_foreign_key(
        "fk_conversations_avatar_asset_id",
        "conversations",
        "media_assets",
        ["avatar_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_conversations_avatar_asset_id", "conversations", type_="foreignkey")
    op.drop_index("ix_conversations_avatar_asset_id", table_name="conversations")
    op.drop_column("conversations", "avatar_asset_id")
