import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.admin.models import OfficialKnowledgeSource, PoiKnowledgeImportJob, StructuredKnowledgeImportJob
from app.modules.ai_rag.types import KnowledgeDomain
from app.workers import domain_handlers


def test_official_indexing_propagates_governance_metadata(monkeypatch) -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        reviewed_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
        source = OfficialKnowledgeSource(
            source_type="poi",
            title="Governed POI",
            body_text="Official POI record.",
            city_code="330100",
            status="indexing",
            reviewed_at=reviewed_at,
            next_review_at=reviewed_at + timedelta(days=90),
            source_version="2.4",
            supersedes_document_id="previous-document",
        )
        async with factory() as session:
            session.add(source)
            await session.commit()

        ingested = []

        class IngestionService:
            def __init__(self, *_args) -> None:
                pass

            async def ingest(self, document) -> None:
                ingested.append(document)

        runtime = SimpleNamespace(
            embeddings=object(),
            catalog=SimpleNamespace(stores={KnowledgeDomain.OFFICIAL: (object(), object())}),
            close=lambda: _close(),
        )
        closed = False

        async def _close() -> None:
            nonlocal closed
            closed = True

        monkeypatch.setattr(domain_handlers, "Settings", lambda: SimpleNamespace(ai_enabled=True))

        async def open_runtime(_settings):
            return runtime

        monkeypatch.setattr(domain_handlers, "open_domain_retrieval_runtime", open_runtime)
        from app.modules.ai_rag import ingestion

        monkeypatch.setattr(ingestion, "KnowledgeIngestionService", IngestionService)
        try:
            async with factory() as session:
                await domain_handlers._index_official_ai_knowledge(
                    session, {"payload": {"knowledge_source_id": source.id}}
                )
                await session.commit()

            assert len(ingested) == 1
            document = ingested[0]
            assert document.knowledge_domain is KnowledgeDomain.OFFICIAL
            assert document.next_review_at == reviewed_at + timedelta(days=90)
            assert document.source_version == "2.4"
            assert document.supersedes_document_id == "previous-document"
            assert closed
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_structured_import_schedules_review_before_queuing_indexing() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                admin = User(phone="13600000072")
                session.add(admin)
                await session.flush()
                job = StructuredKnowledgeImportJob(
                    requested_by=admin.id,
                    city_code="330100",
                    entries=[{"source_type": "rule", "title": "Imported rule", "body_text": "Official rule."}],
                    status="queued",
                )
                session.add(job)
                await session.commit()

            async with factory() as session:
                await domain_handlers._import_structured_knowledge(
                    session, {"payload": {"structured_knowledge_import_job_id": job.id}}
                )
                await session.commit()

            async with factory() as session:
                source = await session.scalar(
                    select(OfficialKnowledgeSource)
                )
                assert source is not None
                assert source.next_review_at == source.reviewed_at + timedelta(days=180)
                assert source.source_version == "1"
                assert source.supersedes_document_id is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_poi_import_assigns_an_explicit_initial_source_version(monkeypatch) -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                admin = User(phone="13600000073")
                session.add(admin)
                await session.flush()
                job = PoiKnowledgeImportJob(
                    requested_by=admin.id,
                    city_code="110000",
                    keywords=["Forbidden City"],
                )
                session.add(job)
                await session.commit()

            class Maps:
                async def search_pois(self, _keyword: str, _city_code: str):
                    return [SimpleNamespace(
                        id="amap-forbidden-city",
                        name="Forbidden City",
                        address="Beijing",
                        adcode="110101",
                    )]

            monkeypatch.setattr(domain_handlers, "AMapService", Maps)
            async with factory() as session:
                await domain_handlers._import_poi_knowledge(
                    session, {"payload": {"poi_knowledge_import_job_id": job.id}}
                )
                await session.commit()

            async with factory() as session:
                source = await session.scalar(select(OfficialKnowledgeSource))
                assert source is not None
                assert source.source_version == "1"
        finally:
            await engine.dispose()

    asyncio.run(scenario())
