"""Create structured knowledge import job facts.

Revision ID: 20260806_0014
Revises: 20260806_0013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260806_0014"
down_revision = "20260806_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "structured_knowledge_import_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("city_code", sa.String(32), nullable=False),
        sa.Column("entries", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_structured_knowledge_import_jobs_status"),
        sa.CheckConstraint("imported_count >= 0", name="ck_structured_knowledge_import_jobs_imported_count"),
        sa.CheckConstraint("skipped_count >= 0", name="ck_structured_knowledge_import_jobs_skipped_count"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name="fk_structured_knowledge_import_jobs_requested_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_structured_knowledge_import_jobs"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_structured_knowledge_import_jobs_requested_by", "structured_knowledge_import_jobs", ["requested_by"])
    op.create_index("ix_structured_knowledge_import_jobs_city_code", "structured_knowledge_import_jobs", ["city_code"])
    op.create_index("ix_structured_knowledge_import_jobs_status", "structured_knowledge_import_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("structured_knowledge_import_jobs")
