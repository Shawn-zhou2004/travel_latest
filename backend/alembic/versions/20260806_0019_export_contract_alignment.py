"""Align export task facts with DOCX and event contracts.

Revision ID: 20260806_0019
Revises: 20260806_0018
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0019"
down_revision = "20260806_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("media_assets", "mime_type", existing_type=sa.String(32), type_=sa.String(128), existing_nullable=False)
    op.add_column("export_tasks", sa.Column("itinerary_version_id", sa.String(36), nullable=True))
    op.execute(
        "UPDATE export_tasks AS task "
        "JOIN itinerary_versions AS version ON version.itinerary_id = task.itinerary_id AND version.version = task.version_no "
        "SET task.itinerary_version_id = version.id"
    )
    op.alter_column("export_tasks", "itinerary_version_id", existing_type=sa.String(36), nullable=False)
    op.create_foreign_key(
        "fk_export_tasks_itinerary_version_id_itinerary_versions",
        "export_tasks",
        "itinerary_versions",
        ["itinerary_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_export_tasks_itinerary_version_id", "export_tasks", ["itinerary_version_id"])


def downgrade() -> None:
    op.drop_constraint("fk_export_tasks_itinerary_version_id_itinerary_versions", "export_tasks", type_="foreignkey")
    op.drop_index("ix_export_tasks_itinerary_version_id", table_name="export_tasks")
    op.drop_column("export_tasks", "itinerary_version_id")
    op.alter_column("media_assets", "mime_type", existing_type=sa.String(128), type_=sa.String(32), existing_nullable=False)
