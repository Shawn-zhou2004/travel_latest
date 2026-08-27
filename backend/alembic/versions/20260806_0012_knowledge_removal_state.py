"""Add safe removal state for indexed AI knowledge.

Revision ID: 20260806_0012
Revises: 20260806_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0012"
down_revision = "20260806_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("official_knowledge_sources", sa.Column("removal_error", sa.String(500), nullable=True))
    op.drop_constraint("ck_official_knowledge_status", "official_knowledge_sources", type_="check")
    op.create_check_constraint(
        "ck_official_knowledge_status",
        "official_knowledge_sources",
        "status IN ('draft', 'pending_review', 'indexing', 'indexed', 'removing', 'failed', 'rejected', 'inactive')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_official_knowledge_status", "official_knowledge_sources", type_="check")
    op.create_check_constraint(
        "ck_official_knowledge_status",
        "official_knowledge_sources",
        "status IN ('draft', 'pending_review', 'indexing', 'indexed', 'failed', 'rejected', 'inactive')",
    )
    op.drop_column("official_knowledge_sources", "removal_error")
