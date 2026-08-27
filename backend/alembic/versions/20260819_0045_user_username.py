"""Add username to users for fixed backoffice accounts.

Revision ID: 20260819_0045
Revises: 20260819_0044
Create Date: 2026-08-19

"""

import sqlalchemy as sa
from alembic import op

revision = "20260819_0045"
down_revision = "20260819_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(length=64), nullable=True))
    op.create_index("uq_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_username", table_name="users")
    op.drop_column("users", "username")
