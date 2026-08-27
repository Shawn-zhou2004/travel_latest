"""Add the active rebuild uniqueness key.

Revision ID: 20260809_0032
Revises: 20260809_0031
"""

from alembic import op
import sqlalchemy as sa

revision = "20260809_0032"
down_revision = "20260809_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_index_rebuild_jobs", sa.Column("active_key", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_search_index_rebuild_active_key", "search_index_rebuild_jobs", ["active_key"])


def downgrade() -> None:
    op.drop_constraint("uq_search_index_rebuild_active_key", "search_index_rebuild_jobs", type_="unique")
    op.drop_column("search_index_rebuild_jobs", "active_key")
