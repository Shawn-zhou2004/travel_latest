"""Create community, chat, notification, and search projection tables.

Revision ID: 20260801_0003
Revises: 20260801_0002
Create Date: 2026-08-01 00:03:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260801_0003"
down_revision = "20260801_0002"
branch_labels = None
depends_on = None


def _options() -> dict[str, str]:
    return {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)
    op.create_table("posts", sa.Column("id", sa.String(36), primary_key=True), sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("content_type", sa.String(24), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("body_text", sa.Text(), nullable=False), sa.Column("city_code", sa.String(32)), sa.Column("status", sa.String(24), nullable=False), sa.Column("moderation_reason", sa.String(500)), sa.Column("sanitized_snapshot_json", mysql.JSON()), sa.Column("published_at", timestamp), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("status IN ('draft', 'pending_review', 'published', 'hidden', 'rejected')", name="ck_posts_status"), sa.CheckConstraint("content_type IN ('note', 'itinerary')", name="ck_posts_content_type"), **_options())
    op.create_index("ix_posts_public_feed", "posts", ["status", "city_code", "published_at"])
    op.create_table("post_media", sa.Column("id", sa.String(36), primary_key=True), sa.Column("post_id", sa.String(36), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False), sa.Column("media_id", sa.String(36), nullable=False), sa.Column("sort_order", sa.Integer(), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), **_options())
    op.create_index("ix_post_media_post_id", "post_media", ["post_id"])
    op.create_table("post_reactions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("post_id", sa.String(36), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("reaction_type", sa.String(24), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.UniqueConstraint("post_id", "user_id", name="uq_post_reactions_post_user"), **_options())
    op.create_table("post_favorites", sa.Column("id", sa.String(36), primary_key=True), sa.Column("post_id", sa.String(36), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.UniqueConstraint("post_id", "user_id", name="uq_post_favorites_post_user"), **_options())
    op.create_table("comments", sa.Column("id", sa.String(36), primary_key=True), sa.Column("post_id", sa.String(36), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False), sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("parent_id", sa.String(36), sa.ForeignKey("comments.id", ondelete="SET NULL")), sa.Column("body_text", sa.Text(), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("status IN ('visible', 'hidden')", name="ck_comments_status"), **_options())
    op.create_index("ix_comments_post_id", "comments", ["post_id"])
    op.create_table("content_reports", sa.Column("id", sa.String(36), primary_key=True), sa.Column("reporter_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("target_type", sa.String(16), nullable=False), sa.Column("target_id", sa.String(36), nullable=False), sa.Column("reason_code", sa.String(64), nullable=False), sa.Column("detail", sa.String(500)), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("target_type IN ('post', 'comment')", name="ck_content_reports_target_type"), **_options())
    op.create_table("companion_requests", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("city_code", sa.String(32)), sa.Column("description", sa.Text(), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("status IN ('open', 'closed', 'cancelled')", name="ck_companion_requests_status"), **_options())
    op.create_table("companion_applications", sa.Column("id", sa.String(36), primary_key=True), sa.Column("request_id", sa.String(36), sa.ForeignKey("companion_requests.id", ondelete="CASCADE"), nullable=False), sa.Column("applicant_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("message", sa.String(1000), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'withdrawn')", name="ck_companion_applications_status"), sa.UniqueConstraint("request_id", "applicant_id", name="uq_companion_applications_request_applicant"), **_options())
    op.create_table("conversations", sa.Column("id", sa.String(36), primary_key=True), sa.Column("conversation_type", sa.String(24), nullable=False), sa.Column("direct_key", sa.String(80), unique=True), sa.Column("title", sa.String(200)), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("conversation_type IN ('direct', 'companion_group')", name="ck_conversations_type"), **_options())
    op.create_table("conversation_members", sa.Column("id", sa.String(36), primary_key=True), sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("joined_at", timestamp, nullable=False), sa.Column("left_at", timestamp), sa.Column("last_read_message_id", sa.String(36)), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.UniqueConstraint("conversation_id", "user_id", name="uq_conversation_members_conversation_user"), **_options())
    op.create_table("messages", sa.Column("id", sa.String(36), primary_key=True), sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False), sa.Column("sender_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("client_message_id", sa.String(80), nullable=False), sa.Column("message_type", sa.String(24), nullable=False), sa.Column("body_text", sa.Text()), sa.Column("payload_json", mysql.JSON()), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("message_type IN ('text', 'image', 'location', 'itinerary_card')", name="ck_messages_type"), sa.UniqueConstraint("conversation_id", "sender_id", "client_message_id", name="uq_messages_conversation_sender_client_id"), **_options())
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_table("user_blocks", sa.Column("id", sa.String(36), primary_key=True), sa.Column("blocker_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("blocked_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.CheckConstraint("blocker_id <> blocked_id", name="ck_user_blocks_distinct_users"), sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocks_blocker_blocked"), **_options())
    op.create_table("notifications", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("notification_type", sa.String(64), nullable=False), sa.Column("payload_json", mysql.JSON(), nullable=False), sa.Column("read_at", timestamp), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), **_options())
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_table("search_projections", sa.Column("id", sa.String(36), primary_key=True), sa.Column("document_type", sa.String(32), nullable=False), sa.Column("document_id", sa.String(36), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("indexed_at", timestamp), sa.Column("unavailable_reason", sa.String(200)), sa.Column("created_at", timestamp, nullable=False), sa.Column("updated_at", timestamp, nullable=False), sa.UniqueConstraint("document_type", "document_id", name="uq_search_projections_document"), **_options())


def downgrade() -> None:
    for table in ("search_projections", "notifications", "user_blocks", "messages", "conversation_members", "conversations", "companion_applications", "companion_requests", "content_reports", "comments", "post_favorites", "post_reactions", "post_media", "posts"):
        op.drop_table(table)
