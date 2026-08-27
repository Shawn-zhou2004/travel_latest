"""Add password_hash to users for password login.

Revision ID: 20260819_0044
Revises: 20260813_0043
Create Date: 2026-08-19

"""

import sqlalchemy as sa
from alembic import op

revision = "20260819_0044"
down_revision = "20260813_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
