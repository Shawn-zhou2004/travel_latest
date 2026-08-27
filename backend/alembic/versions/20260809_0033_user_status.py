"""Add persisted user account status.

Revision ID: 20260809_0033
Revises: 20260809_0032
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_0033"
down_revision = "20260809_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
    )
    op.create_check_constraint("ck_users_status", "users", "status IN ('active', 'suspended')")
    op.alter_column("users", "status", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_column("users", "status")
