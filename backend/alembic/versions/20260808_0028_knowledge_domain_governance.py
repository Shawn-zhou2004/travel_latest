"""Add governance metadata to official knowledge sources.

Revision ID: 20260808_0028
Revises: 20260808_0027
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260808_0028"
down_revision = "20260808_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.add_column(
        "official_knowledge_sources",
        sa.Column(
            "knowledge_domain",
            sa.String(16),
            nullable=False,
            server_default="official",
        ),
    )
    op.add_column(
        "official_knowledge_sources",
        sa.Column("next_review_at", timestamp, nullable=True),
    )
    op.add_column(
        "official_knowledge_sources",
        sa.Column(
            "source_version",
            sa.String(64),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "official_knowledge_sources",
        sa.Column("supersedes_document_id", sa.String(36), nullable=True),
    )
    op.create_check_constraint(
        "ck_oks_domain",
        "official_knowledge_sources",
        "knowledge_domain IN ('official', 'community')",
    )
    op.create_foreign_key(
        "fk_oks_supersedes",
        "official_knowledge_sources",
        "official_knowledge_sources",
        ["supersedes_document_id"],
        ["id"],
    )
    op.create_index(
        "ix_oks_domain_status_city",
        "official_knowledge_sources",
        ["knowledge_domain", "status", "city_code"],
    )
    op.create_index(
        "ix_oks_next_review",
        "official_knowledge_sources",
        ["next_review_at"],
    )
    op.create_index(
        "ix_oks_supersedes",
        "official_knowledge_sources",
        ["supersedes_document_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_oks_supersedes",
        "official_knowledge_sources",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_oks_domain",
        "official_knowledge_sources",
        type_="check",
    )
    op.drop_index("ix_oks_supersedes", table_name="official_knowledge_sources")
    op.drop_index("ix_oks_next_review", table_name="official_knowledge_sources")
    op.drop_index("ix_oks_domain_status_city", table_name="official_knowledge_sources")
    op.drop_column("official_knowledge_sources", "supersedes_document_id")
    op.drop_column("official_knowledge_sources", "source_version")
    op.drop_column("official_knowledge_sources", "next_review_at")
    op.drop_column("official_knowledge_sources", "knowledge_domain")
