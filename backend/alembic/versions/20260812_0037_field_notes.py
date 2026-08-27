"""Add field-note persistence and itinerary copy idempotency facts.

Revision ID: 20260812_0037
Revises: 20260811_0036
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260812_0037"
down_revision = "20260811_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("itinerary_id", sa.String(36), nullable=True))
    op.add_column("posts", sa.Column("itinerary_version_id", sa.String(36), nullable=True))
    op.add_column("posts", sa.Column("itinerary_snapshot_json", mysql.JSON(), nullable=True))
    op.add_column("posts", sa.Column("recap_text", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("cover_media_id", sa.String(36), nullable=True))
    op.add_column("posts", sa.Column("copy_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_posts_copy_count_nonnegative", "posts", "copy_count >= 0")
    op.create_foreign_key("fk_posts_itinerary_id", "posts", "itineraries", ["itinerary_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(
        "fk_posts_itinerary_version_id",
        "posts",
        "itinerary_versions",
        ["itinerary_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key("fk_posts_cover_media_id", "posts", "media_assets", ["cover_media_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_posts_itinerary_id", "posts", ["itinerary_id"])
    op.create_index("ix_posts_itinerary_version_id", "posts", ["itinerary_version_id"])

    op.add_column("itineraries", sa.Column("source_post_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_itineraries_source_post_id", "itineraries", "posts", ["source_post_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_itineraries_source_post_id", "itineraries", ["source_post_id"])

    op.create_table(
        "itinerary_copy_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("source_post_id", sa.String(36), nullable=False),
        sa.Column("itinerary_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["itinerary_id"], ["itineraries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("actor_id", "source_post_id", "idempotency_key", name="uq_itinerary_copy_operations_actor_source_key"),
        sa.UniqueConstraint("itinerary_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def has_column(table_name: str, column_name: str) -> bool:
        return column_name in {column["name"] for column in inspector.get_columns(table_name)}

    def has_foreign_key(table_name: str, constraint_name: str) -> bool:
        return constraint_name in {constraint["name"] for constraint in inspector.get_foreign_keys(table_name)}

    def has_index(table_name: str, index_name: str) -> bool:
        return index_name in {index["name"] for index in inspector.get_indexes(table_name)}

    def has_check(table_name: str, constraint_name: str) -> bool:
        return constraint_name in {constraint["name"] for constraint in inspector.get_check_constraints(table_name)}

    if "itinerary_copy_operations" in inspector.get_table_names():
        op.drop_table("itinerary_copy_operations")

    if has_foreign_key("itineraries", "fk_itineraries_source_post_id"):
        op.drop_constraint("fk_itineraries_source_post_id", "itineraries", type_="foreignkey")
    if has_index("itineraries", "ix_itineraries_source_post_id"):
        op.drop_index("ix_itineraries_source_post_id", table_name="itineraries")
    if has_column("itineraries", "source_post_id"):
        op.drop_column("itineraries", "source_post_id")

    for constraint_name in ("fk_posts_cover_media_id", "fk_posts_itinerary_version_id", "fk_posts_itinerary_id"):
        if has_foreign_key("posts", constraint_name):
            op.drop_constraint(constraint_name, "posts", type_="foreignkey")
    for index_name in ("ix_posts_itinerary_version_id", "ix_posts_itinerary_id"):
        if has_index("posts", index_name):
            op.drop_index(index_name, table_name="posts")
    if has_check("posts", "ck_posts_copy_count_nonnegative"):
        op.drop_constraint("ck_posts_copy_count_nonnegative", "posts", type_="check")
    for column_name in ("copy_count", "cover_media_id", "recap_text", "itinerary_snapshot_json", "itinerary_version_id", "itinerary_id"):
        if has_column("posts", column_name):
            op.drop_column("posts", column_name)
