"""Create durable community knowledge review facts.

Revision ID: 20260808_0029
Revises: 20260808_0028
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260808_0029"
down_revision = "20260808_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table(
        "community_knowledge_reviews",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("post_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_ckr_status"
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE", name="fk_ckr_post"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_ckr_reviewer"),
        sa.PrimaryKeyConstraint("id", name="pk_ckr"),
        sa.UniqueConstraint("post_id", name="uq_ckr_post"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_ckr_status_created",
        "community_knowledge_reviews",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_ckr_reviewer_reviewed",
        "community_knowledge_reviews",
        ["reviewed_by", "reviewed_at"],
    )


def downgrade() -> None:
    op.drop_table("community_knowledge_reviews")
