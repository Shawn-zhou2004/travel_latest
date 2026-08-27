"""Expand allowed generation job statuses.

Revision ID: 20260810_0034
Revises: 20260809_0033
"""

from alembic import op


revision = "20260810_0034"
down_revision = "20260809_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_generation_jobs_status", "generation_jobs", type_="check")
    op.create_check_constraint(
        "ck_generation_jobs_status",
        "generation_jobs",
        "status IN ('queued', 'understanding', 'resolving_destination', 'retrieving', "
        "'retrieving_reviewed_sources', 'searching_live_sources', 'verifying_pois', "
        "'planning', 'validating', 'awaiting_confirmation', 'succeeded', 'failed', "
        "'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_generation_jobs_status", "generation_jobs", type_="check")
    op.create_check_constraint(
        "ck_generation_jobs_status",
        "generation_jobs",
        "status IN ('queued', 'understanding', 'retrieving', 'planning', 'validating', "
        "'awaiting_confirmation', 'succeeded', 'failed', 'cancelled')",
    )
