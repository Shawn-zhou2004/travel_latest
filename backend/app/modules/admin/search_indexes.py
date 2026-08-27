from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.settings import Settings
from app.models.base import new_uuid
from app.models.outbox import OutboxEvent
from app.modules.admin.models import AdminAction, SearchIndexRebuildJob

SEARCH_INDEXES: tuple[tuple[str, str], ...] = (
    ("travel_knowledge", "elasticsearch_index_travel_knowledge"),
    ("official_knowledge", "elasticsearch_index_official_knowledge"),
    ("community_knowledge", "elasticsearch_index_community_knowledge"),
    ("user_memory", "elasticsearch_index_user_memory"),
)
ACTIVE_REBUILD_STATUSES = ("queued", "running")


def rebuild_job_item(job: SearchIndexRebuildJob) -> dict[str, Any]:
    return {field: getattr(job, field) for field in (
        "id", "index_name", "requested_by", "status", "progress", "error",
        "created_at", "updated_at", "started_at", "completed_at",
    )}


async def queue_rebuild_job(session: Any, claims: Any, index_name: str) -> tuple[SearchIndexRebuildJob, bool]:
    allowed = {logical_name for logical_name, _ in SEARCH_INDEXES}
    if index_name not in allowed:
        raise ValueError(f"Unknown search index logical name: {index_name}")
    active = await session.scalar(
        select(SearchIndexRebuildJob)
        .where(SearchIndexRebuildJob.index_name == index_name, SearchIndexRebuildJob.status.in_(ACTIVE_REBUILD_STATUSES))
        .order_by(SearchIndexRebuildJob.created_at.desc())
        .with_for_update()
    )
    if active is not None:
        return active, False
    job = SearchIndexRebuildJob(index_name=index_name, active_key=index_name, requested_by=claims.user_id)
    session.add(job)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        active = await session.scalar(select(SearchIndexRebuildJob).where(SearchIndexRebuildJob.active_key == index_name))
        if active is not None:
            return active, False
        raise
    session.add(OutboxEvent(
        event_type="admin.search_index_rebuild_requested",
        aggregate_type="search_index_rebuild_job",
        aggregate_id=job.id,
        trace_id=new_uuid(),
        payload_json={"job_id": job.id, "index_name": index_name},
    ))
    session.add(AdminAction(
        actor_id=claims.user_id,
        action="search_index_rebuild.queued",
        target_type="search_index_rebuild_job",
        target_id=job.id,
        reason=f"Requested rebuild of {index_name}.",
        result_json={"index_name": index_name, "status": job.status},
    ))
    return job, True


class SearchIndexInventoryService:
    def __init__(self, settings: Settings, client_factory: Callable[[str | Sequence[str]], Any] | None = None) -> None:
        self.settings = settings
        self.client_factory = client_factory or self._default_client

    @staticmethod
    def _default_client(hosts: str | Sequence[str]) -> Any:
        from elasticsearch import AsyncElasticsearch

        return AsyncElasticsearch(hosts=hosts)

    def configured_indexes(self) -> list[tuple[str, str]]:
        return [(logical_name, getattr(self.settings, setting_name)) for logical_name, setting_name in SEARCH_INDEXES]

    async def inventory(self) -> list[dict[str, Any]]:
        configured = self.configured_indexes()
        if not self.settings.elasticsearch_url:
            return [self._item(logical_name, index_name, "unavailable", None, "Elasticsearch is not configured.") for logical_name, index_name in configured]
        client = None
        try:
            client = self.client_factory(self.settings.elasticsearch_url)
            await client.info()
        except Exception:
            await self._close(client)
            return [self._item(logical_name, index_name, "unavailable", None, "Elasticsearch is unavailable.") for logical_name, index_name in configured]
        results = []
        for logical_name, index_name in configured:
            try:
                if not await client.indices.exists(index=index_name):
                    results.append(self._item(logical_name, index_name, "empty", 0, None))
                    continue
                count = int((await client.count(index=index_name)).get("count", 0))
                results.append(self._item(logical_name, index_name, "healthy" if count else "empty", count, None))
            except Exception as error:
                results.append(self._item(logical_name, index_name, "degraded", None, str(error)))
        await self._close(client)
        return results

    @staticmethod
    def _item(logical_name: str, index_name: str, status: str, document_count: int | None, message: str | None) -> dict[str, Any]:
        return {"logical_name": logical_name, "index_name": index_name, "status": status, "document_count": document_count, "message": message}

    @staticmethod
    async def _close(client: Any) -> None:
        if client is None:
            return
        close = getattr(client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
