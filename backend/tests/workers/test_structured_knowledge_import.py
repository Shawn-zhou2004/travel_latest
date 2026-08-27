import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.admin.models import OfficialKnowledgeSource, StructuredKnowledgeImportJob
from app.workers.domain_handlers import _import_structured_knowledge


def test_structured_knowledge_import_creates_indexing_sources() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                admin = User(phone="13600000024")
                session.add(admin)
                await session.flush()
                job = StructuredKnowledgeImportJob(
                    requested_by=admin.id,
                    city_code="330100",
                    entries=[
                        {"source_type": "rule", "title": "Lakeside pacing", "body_text": "Leave time between lakeside stops."},
                        {"source_type": "template", "title": "One-day lakeside", "body_text": "Start near the lake in the morning."},
                    ],
                )
                session.add(job)
                await session.commit()

            async with factory() as session:
                await _import_structured_knowledge(session, {"payload": {"structured_knowledge_import_job_id": job.id}})
                await session.commit()

            async with factory() as session:
                stored_job = await session.get(StructuredKnowledgeImportJob, job.id)
                sources = (await session.scalars(select(OfficialKnowledgeSource).order_by(OfficialKnowledgeSource.source_type))).all()
                events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "ai.official_knowledge_index_requested"))).all()
                assert stored_job is not None
                assert stored_job.status == "succeeded"
                assert stored_job.imported_count == 2
                assert stored_job.skipped_count == 0
                assert [source.source_type for source in sources] == ["rule", "template"]
                assert all(source.status == "indexing" for source in sources)
                assert len(events) == 2
        finally:
            await engine.dispose()

    asyncio.run(scenario())
