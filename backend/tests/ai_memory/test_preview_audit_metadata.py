from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date

import pytest

from app.modules.ai_memory.postgres import AIMemoryRepository, SCHEMA_SQL
from app.modules.ai_workflows.contracts import (
    GenerationRequest,
    NodeAudit,
    VerifiedItineraryDraft,
)


class RecordingConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query: str, *args: object) -> str:
        self.executed.append((query, args))
        return "INSERT 0 1"

    async def fetchrow(self, query: str, *args: object) -> dict[str, str] | None:
        if "INSERT INTO ai_generation_previews" in query:
            return {"id": "preview-1"}
        return None


class RecordingPool:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def test_preview_audit_schema_adds_metadata_columns_idempotently() -> None:
    for column in (
        "agent_version TEXT",
        "duration_ms INTEGER",
        "redacted_summary TEXT",
        "tool_summary JSONB",
        "degradations JSONB",
        "review_codes JSONB",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in SCHEMA_SQL


@pytest.mark.anyio
async def test_save_preview_writes_safe_extended_audit_metadata() -> None:
    connection = RecordingConnection()
    repository = AIMemoryRepository(RecordingPool(connection))
    request = GenerationRequest(
        generation_job_id="job-1",
        user_id="user-1",
        prompt="raw prompt must not be stored with the audit",
        city_code="SHA",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 11),
    )
    audit = NodeAudit(
        node="draft",
        status="degraded",
        agent_version="itinerary-agent@2026.08",
        duration_ms=125,
        redacted_summary="Generated a one-day draft without sensitive inputs.",
        tool_summary={"poi_verify": "completed", "calls": 2},
        degradations=("weather-unavailable",),
        review_codes=("manual-review",),
    )

    preview = await repository.save_preview(
        request, VerifiedItineraryDraft(title="Shanghai", days=()), (), (audit,)
    )

    assert preview.preview_id
    audit_query, audit_args = connection.executed[-1]
    assert "INSERT INTO ai_preview_audits" in audit_query
    assert audit_args[3:] == (
        "draft",
        "degraded",
        "itinerary-agent@2026.08",
        125,
        "Generated a one-day draft without sensitive inputs.",
        '{"poi_verify": "completed", "calls": 2}',
        '["weather-unavailable"]',
        '["manual-review"]',
    )
    assert request.prompt not in audit_query
    assert request.prompt not in audit_args


def test_node_audit_legacy_construction_remains_supported() -> None:
    audit = NodeAudit(node="retrieve", status="completed")

    assert audit.agent_version is None
    assert audit.duration_ms is None
    assert audit.redacted_summary is None
    assert audit.tool_summary is None
    assert audit.degradations == ()
    assert audit.review_codes == ()
