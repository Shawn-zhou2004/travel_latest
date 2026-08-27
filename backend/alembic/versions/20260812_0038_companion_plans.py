"""Persist itinerary-backed companion plan facts.

Revision ID: 20260812_0038
Revises: 20260812_0037
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260812_0038"
down_revision = "20260812_0037"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _foreign_keys(table_name: str) -> set[str]:
    return {foreign_key["name"] for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _checks(table_name: str) -> set[str]:
    return {check["name"] for check in sa.inspect(op.get_bind()).get_check_constraints(table_name)}


def upgrade() -> None:
    request_columns = {
        "itinerary_id": sa.Column("itinerary_id", sa.String(36), nullable=True),
        "trip_kind": sa.Column("trip_kind", sa.String(16), nullable=True),
        "start_date": sa.Column("start_date", sa.Date(), nullable=True),
        "end_date": sa.Column("end_date", sa.Date(), nullable=True),
        "party_size": sa.Column("party_size", sa.Integer(), nullable=True),
        # A server default safely fills historical rows during MySQL's nontransactional ALTER TABLE.
        "accepted_count": sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="1"),
        "budget_min": sa.Column("budget_min", sa.DECIMAL(10, 2), nullable=True),
        "budget_max": sa.Column("budget_max", sa.DECIMAL(10, 2), nullable=True),
        "currency": sa.Column("currency", sa.String(3), nullable=True),
        "travel_pace": sa.Column("travel_pace", sa.String(16), nullable=True),
        "interest_tags": sa.Column("interest_tags", mysql.JSON(), nullable=True),
        "intro_text": sa.Column("intro_text", sa.Text(), nullable=True),
        "conversation_id": sa.Column("conversation_id", sa.String(36), nullable=True),
    }
    for name, column in request_columns.items():
        if name not in _columns("companion_requests"):
            op.add_column("companion_requests", column)

    if "conversation_id" not in _columns("companion_applications"):
        op.add_column("companion_applications", sa.Column("conversation_id", sa.String(36), nullable=True))

    if "ck_companion_requests_status" in _checks("companion_requests"):
        op.drop_constraint("ck_companion_requests_status", "companion_requests", type_="check")
    checks = {
        "ck_companion_requests_status": "status IN ('open', 'full', 'closed', 'cancelled', 'completed')",
        "ck_companion_requests_date_order": "start_date IS NULL OR end_date IS NULL OR start_date <= end_date",
        "ck_companion_requests_party_size": "party_size IS NULL OR party_size >= 2",
        "ck_companion_requests_accepted_count": "accepted_count >= 1 AND (party_size IS NULL OR accepted_count <= party_size)",
        "ck_companion_requests_budget_order": "budget_min IS NULL OR budget_max IS NULL OR budget_min <= budget_max",
        "ck_companion_requests_trip_kind": "trip_kind IS NULL OR trip_kind IN ('trip', 'activity')",
        "ck_companion_requests_travel_pace": "travel_pace IS NULL OR travel_pace IN ('slow', 'balanced', 'packed')",
    }
    for name, condition in checks.items():
        if name not in _checks("companion_requests"):
            op.create_check_constraint(name, "companion_requests", condition)

    indexes = (
        ("ix_companion_requests_public_discovery", ["review_status", "status", "start_date"]),
        ("ix_companion_requests_city_code", ["city_code"]),
        ("ix_companion_requests_trip_kind", ["trip_kind"]),
        ("ix_companion_requests_itinerary_id", ["itinerary_id"]),
        ("ix_companion_requests_conversation_id", ["conversation_id"]),
    )
    for name, columns in indexes:
        if name not in _indexes("companion_requests"):
            op.create_index(name, "companion_requests", columns)
    if "ix_companion_applications_conversation_id" not in _indexes("companion_applications"):
        op.create_index("ix_companion_applications_conversation_id", "companion_applications", ["conversation_id"])

    foreign_keys = (
        ("fk_companion_requests_itinerary_id", "companion_requests", "itineraries", ["itinerary_id"]),
        ("fk_companion_requests_conversation_id", "companion_requests", "conversations", ["conversation_id"]),
        ("fk_companion_applications_conversation_id", "companion_applications", "conversations", ["conversation_id"]),
    )
    for name, source, target, columns in foreign_keys:
        if name not in _foreign_keys(source):
            op.create_foreign_key(name, source, target, columns, ["id"], ondelete="SET NULL")


def downgrade() -> None:
    # MySQL requires foreign keys to be removed before indexes that support them.
    for name, table_name in (
        ("fk_companion_applications_conversation_id", "companion_applications"),
        ("fk_companion_requests_conversation_id", "companion_requests"),
        ("fk_companion_requests_itinerary_id", "companion_requests"),
    ):
        if name in _foreign_keys(table_name):
            op.drop_constraint(name, table_name, type_="foreignkey")

    for name in (
        "ix_companion_requests_conversation_id",
        "ix_companion_requests_itinerary_id",
        "ix_companion_requests_trip_kind",
        "ix_companion_requests_city_code",
        "ix_companion_requests_public_discovery",
    ):
        if name in _indexes("companion_requests"):
            op.drop_index(name, table_name="companion_requests")
    if "ix_companion_applications_conversation_id" in _indexes("companion_applications"):
        op.drop_index("ix_companion_applications_conversation_id", table_name="companion_applications")

    for name in (
        "ck_companion_requests_travel_pace",
        "ck_companion_requests_trip_kind",
        "ck_companion_requests_budget_order",
        "ck_companion_requests_accepted_count",
        "ck_companion_requests_party_size",
        "ck_companion_requests_date_order",
        "ck_companion_requests_status",
    ):
        if name in _checks("companion_requests"):
            op.drop_constraint(name, "companion_requests", type_="check")
    if "ck_companion_requests_status" not in _checks("companion_requests"):
        op.create_check_constraint(
            "ck_companion_requests_status", "companion_requests", "status IN ('open', 'closed', 'cancelled')"
        )

    if "conversation_id" in _columns("companion_applications"):
        op.drop_column("companion_applications", "conversation_id")
    for name in (
        "conversation_id",
        "intro_text",
        "interest_tags",
        "travel_pace",
        "currency",
        "budget_max",
        "budget_min",
        "accepted_count",
        "party_size",
        "end_date",
        "start_date",
        "trip_kind",
        "itinerary_id",
    ):
        if name in _columns("companion_requests"):
            op.drop_column("companion_requests", name)
