import asyncio
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.admin.models import CommunityKnowledgeReview
from app.modules.ai_rag.types import KnowledgeDomain
from app.modules.community.models import Post
from app.workers import domain_handlers


def test_only_approved_published_community_posts_are_indexed(monkeypatch) -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                author = User(phone="13600000901")
                session.add(author)
                await session.flush()
                post = Post(author_id=author.id, content_type="note", title="Reviewed route", body_text="Leave early.", city_code="330100", status="published")
                session.add(post)
                await session.flush()
                session.add(CommunityKnowledgeReview(post_id=post.id, status="approved"))
                await session.commit()

            documents = []

            class IngestionService:
                def __init__(self, *_args) -> None:
                    pass

                async def ingest(self, document) -> None:
                    documents.append(document)

            async def close() -> None:
                return None

            class MilvusStore:
                async def ensure_collection(self) -> None:
                    return None

            runtime = SimpleNamespace(
                embeddings=object(),
                catalog=SimpleNamespace(stores={KnowledgeDomain.COMMUNITY: (MilvusStore(), object())}),
                close=close,
            )
            monkeypatch.setattr(domain_handlers, "Settings", lambda: SimpleNamespace(ai_enabled=True))
            monkeypatch.setattr(domain_handlers, "open_domain_retrieval_runtime", lambda _settings: _async_value(runtime))
            from app.modules.ai_rag import ingestion

            monkeypatch.setattr(ingestion, "KnowledgeIngestionService", IngestionService)
            async with factory() as session:
                await domain_handlers._index_approved_community_knowledge(session, {"payload": {"post_id": post.id}})

            assert len(documents) == 1
            assert documents[0].document_id == post.id
            assert documents[0].knowledge_domain is KnowledgeDomain.COMMUNITY

            async with factory() as session:
                review = await session.scalar(select(CommunityKnowledgeReview).where(CommunityKnowledgeReview.post_id == post.id))
                assert review is not None
                review.status = "rejected"
                await session.commit()
            async with factory() as session:
                await domain_handlers._index_approved_community_knowledge(session, {"payload": {"post_id": post.id}})
            assert len(documents) == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())


async def _async_value(value):
    return value
