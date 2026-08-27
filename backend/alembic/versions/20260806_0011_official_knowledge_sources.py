"""Create reviewed official AI knowledge sources.

Revision ID: 20260806_0011
Revises: 20260805_0010
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260806_0011"
down_revision = "20260805_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "official_knowledge_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("city_code", sa.String(32), nullable=True),
        sa.Column("poi_id", sa.String(128), nullable=True),
        sa.Column("language", sa.String(16), nullable=False, server_default="zh-CN"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("review_reason", sa.String(500), nullable=True),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", timestamp, nullable=True),
        sa.Column("indexed_at", timestamp, nullable=True),
        sa.Column("index_error", sa.String(500), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("source_type IN ('rule', 'template', 'poi')", name="ck_official_knowledge_source_type"),
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'indexing', 'indexed', 'failed', 'rejected', 'inactive')", name="ck_official_knowledge_status"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_official_knowledge_reviewed_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_official_knowledge_sources"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_official_knowledge_sources_source_type", "official_knowledge_sources", ["source_type"])
    op.create_index("ix_official_knowledge_sources_city_code", "official_knowledge_sources", ["city_code"])
    op.create_index("ix_official_knowledge_sources_poi_id", "official_knowledge_sources", ["poi_id"])
    op.create_index("ix_official_knowledge_sources_status", "official_knowledge_sources", ["status"])
    op.create_index("ix_official_knowledge_sources_reviewed_by", "official_knowledge_sources", ["reviewed_by"])


def downgrade() -> None:
    op.drop_table("official_knowledge_sources")
