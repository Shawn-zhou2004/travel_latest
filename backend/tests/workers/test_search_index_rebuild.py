import asyncio
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.admin.models import SearchIndexRebuildJob, WebKnowledgeSearchJob
from app.workers import domain_handlers


def test_unsupported_rebuild_is_durable_failed_with_precise_reason() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                user = User(phone="13600000302")
                session.add(user)
                await session.flush()
                job = SearchIndexRebuildJob(index_name="user_memory", requested_by=user.id)
                session.add(job)
                await session.flush()
                session.add(OutboxEvent(
                    event_type="admin.search_index_rebuild_requested",
                    aggregate_type="search_index_rebuild_job",
                    aggregate_id=job.id,
                    trace_id="11111111-1111-4111-8111-111111111111",
                    payload_json={"job_id": job.id, "index_name": job.index_name},
                ))
                await session.commit()
                job_id = job.id
            async with factory() as session:
                await domain_handlers._rebuild_search_index(session, {"payload": {"job_id": job_id}})
                await session.commit()
            async with factory() as session:
                job = await session.get(SearchIndexRebuildJob, job_id)
                assert job is not None
                assert job.status == "failed"
                assert job.progress == 100
                assert "private" in (job.error or "")
                assert job.started_at is not None and job.completed_at is not None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_rebuild_route_is_registered() -> None:
    domain_handlers.register_domain_handlers()
    route = domain_handlers.registered_routes.snapshot()["admin.search_index_rebuild_requested"][0]
    assert route.consumer_name == "admin.search_index.rebuild"


def test_websearch_terminal_failure_is_durable_and_route_is_registered() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                user = User(phone="13600000303")
                session.add(user)
                await session.flush()
                job = WebKnowledgeSearchJob(
                    requested_by=user.id,
                    city_code="330100",
                    query="West Lake official notice",
                    target_domain="official",
                )
                session.add(job)
                await session.commit()
                job_id = job.id
            async with factory() as session:
                await domain_handlers._finalize_web_knowledge_search_failure(session, {"payload": {"job_id": job_id}})
                await session.commit()
            async with factory() as session:
                job = await session.get(WebKnowledgeSearchJob, job_id)
                assert job is not None
                assert job.status == "failed"
                assert job.error_code == "WEBSEARCH_UNAVAILABLE"
                assert job.error_message is not None and "retrying" in job.error_message
        finally:
            await engine.dispose()

    asyncio.run(scenario())
    domain_handlers.register_domain_handlers()
    route = domain_handlers.registered_routes.snapshot()["ai.web_knowledge_search_requested"][0]
    assert route.consumer_name == "ai.web_knowledge.search"
    assert route.defer_idempotency is True
    assert route.terminal_failure_handler is domain_handlers._finalize_web_knowledge_search_failure
