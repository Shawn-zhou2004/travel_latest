import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from app.modules.ai_memory.postgres import AIMemoryRepository


class Connection:
    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchrow(self, query: str, *args: object):
        if "ai_generation_previews" in query:
            return {
                "id": "preview-1",
                "generation_job_id": "job-1",
                "draft": json.dumps({"title": "City break", "days": []}),
                "prompt_version": None,
                "model_version": None,
                "created_at": datetime(2026, 8, 6, tzinfo=UTC),
            }
        return None

    async def fetch(self, query: str, *args: object):
        return []


class Pool:
    @asynccontextmanager
    async def acquire(self):
        yield Connection()


def test_get_preview_decodes_asyncpg_jsonb_text() -> None:
    async def scenario() -> None:
        preview = await AIMemoryRepository(Pool()).get_preview("user-1", "preview-1")
        assert preview is not None
        assert preview["draft"] == {"title": "City break", "days": []}

    asyncio.run(scenario())
