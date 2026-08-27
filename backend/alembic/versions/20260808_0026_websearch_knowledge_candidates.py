"""Create governed web knowledge search facts.

Revision ID: 20260808_0026
Revises: 20260807_0025
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260808_0026"
down_revision = "20260807_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    op.create_table(
        "web_knowledge_search_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("city_code", sa.String(32), nullable=False),
        sa.Column("query", sa.String(500), nullable=False),
        sa.Column("target_domain", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("provider_name", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("target_domain IN ('official', 'community')", name="ck_web_knowledge_search_jobs_target_domain"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_web_knowledge_search_jobs_status"),
        sa.CheckConstraint("result_count >= 0", name="ck_web_knowledge_search_jobs_result_count"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name="fk_wksj_requester"),
        sa.PrimaryKeyConstraint("id", name="pk_web_knowledge_search_jobs"),
        **options,
    )
    # SQLAlchemy creates these single-column indexes from the model mappings.
    # Creating them again causes a duplicate-key failure on MySQL after the
    # table DDL succeeds, leaving a partially applied non-transactional revision.
    op.create_table(
        "web_knowledge_candidates",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("excerpt", sa.String(4000), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("source_url_hash", sa.String(64), nullable=False),
        sa.Column("source_host", sa.String(255), nullable=False),
        sa.Column("published_at", timestamp, nullable=True),
        sa.Column("fetched_at", timestamp, nullable=True),
        sa.Column("excerpt_hash", sa.String(64), nullable=False),
        sa.Column("city_code", sa.String(32), nullable=False),
        sa.Column("target_domain", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="needs_human_review"),
        sa.Column("review_reason", sa.String(500), nullable=True),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", timestamp, nullable=True),
        sa.Column("external_web_source_id", sa.String(36), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("target_domain IN ('official', 'community')", name="ck_web_knowledge_candidates_target_domain"),
        sa.CheckConstraint("status IN ('needs_human_review', 'approved', 'rejected', 'ingested', 'failed')", name="ck_web_knowledge_candidates_status"),
        sa.ForeignKeyConstraint(["job_id"], ["web_knowledge_search_jobs.id"], ondelete="CASCADE", name="fk_wkc_job"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_wkc_reviewer"),
        sa.PrimaryKeyConstraint("id", name="pk_web_knowledge_candidates"),
        sa.UniqueConstraint("job_id", "source_url_hash", name="uq_web_knowledge_candidates_job_source_url_hash"),
        **options,
    )
    op.create_table(
        "external_web_knowledge_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("target_domain", sa.String(16), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("city_code", sa.String(32), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("source_host", sa.String(255), nullable=False),
        sa.Column("published_at", timestamp, nullable=True),
        sa.Column("fetched_at", timestamp, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_review"),
        sa.Column("review_reason", sa.String(500), nullable=True),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", timestamp, nullable=True),
        sa.Column("indexed_at", timestamp, nullable=True),
        sa.Column("index_error", sa.String(500), nullable=True),
        sa.Column("removal_error", sa.String(500), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("target_domain IN ('official', 'community')", name="ck_external_web_knowledge_sources_target_domain"),
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'indexing', 'indexed', 'removing', 'failed', 'rejected', 'inactive')", name="ck_external_web_knowledge_sources_status"),
        sa.ForeignKeyConstraint(["candidate_id"], ["web_knowledge_candidates.id"], name="fk_ewks_candidate"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_ewks_reviewer"),
        sa.PrimaryKeyConstraint("id", name="pk_external_web_knowledge_sources"),
        sa.UniqueConstraint("candidate_id", name="uq_external_web_knowledge_sources_candidate_id"),
        **options,
    )
    op.create_foreign_key(
        "fk_wkc_external_source",
        "web_knowledge_candidates",
        "external_web_knowledge_sources",
        ["external_web_source_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_web_knowledge_candidates_external_web_source_id",
        "web_knowledge_candidates",
        ["external_web_source_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_web_knowledge_candidates_external_web_source_id", "web_knowledge_candidates", type_="unique")
    op.drop_constraint(
        "fk_wkc_external_source",
        "web_knowledge_candidates",
        type_="foreignkey",
    )
    op.drop_table("external_web_knowledge_sources")
    op.drop_table("web_knowledge_candidates")
    op.drop_table("web_knowledge_search_jobs")
