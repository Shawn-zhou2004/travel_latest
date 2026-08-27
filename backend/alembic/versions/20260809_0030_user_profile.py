"""Add nullable consumer profile fields.

Revision ID: 20260809_0030
Revises: 20260808_0029
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_0030"
down_revision = "20260808_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("nickname", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("avatar_asset_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_asset_id")
    op.drop_column("users", "nickname")
