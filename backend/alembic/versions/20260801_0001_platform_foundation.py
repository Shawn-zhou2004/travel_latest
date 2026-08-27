"""Create platform foundation tables.

Revision ID: 20260801_0001
Revises:
Create Date: 2026-08-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260801_0001"
down_revision = None
branch_labels = None
depends_on = None


def _table_options() -> dict[str, str]:
    return {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    timestamp = mysql.DATETIME(fsp=6)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("phone", name="uq_users_phone"),
        **_table_options(),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("revoked_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_sessions_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        **_table_options(),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table(
        "user_roles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'platform_admin', 'provider_admin', 'provider_staff')",
            name="ck_user_roles_role",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_roles_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_user_roles"),
        sa.UniqueConstraint("user_id", "role", "scope_key", name="uq_user_roles_user_role_scope"),
        **_table_options(),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", timestamp, nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("payload_json", mysql.JSON(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_outbox_events"),
        **_table_options(),
    )
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_unpublished", "outbox_events", ["published_at", "created_at"])
    op.create_table(
        "processed_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("consumer_name", sa.String(length=128), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("processed_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["outbox_events.event_id"], name="fk_processed_events_event_id_outbox_events"),
        sa.PrimaryKeyConstraint("id", name="pk_processed_events"),
        sa.UniqueConstraint("consumer_name", "event_id", name="uq_processed_events_consumer_event"),
        **_table_options(),
    )
    op.create_index("ix_processed_events_event_id", "processed_events", ["event_id"])


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("outbox_events")
    op.drop_table("user_roles")
    op.drop_table("user_sessions")
    op.drop_table("users")
