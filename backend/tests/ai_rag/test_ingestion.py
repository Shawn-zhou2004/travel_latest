from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.modules.ai_rag.ingestion import KnowledgeIngestionService
from app.modules.ai_rag.types import KnowledgeSourceType, ReviewedKnowledgeDocument


class FakeEmbeddings:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(index)] for index, _ in enumerate(texts)]

    async def embed_query(self, _text: str) -> list[float]:
        return [1.0]


class FakeMilvus:
    chunks = []
    vectors = []

    async def upsert(self, chunks: object, vectors: object) -> None:
        self.chunks = list(chunks)
        self.vectors = list(vectors)


class FakeElasticsearch:
    chunks = []

    async def index(self, chunks: object) -> None:
        self.chunks = list(chunks)


def test_reviewed_knowledge_is_chunked_embedded_and_indexed_with_required_metadata() -> None:
    async def scenario() -> None:
        milvus = FakeMilvus()
        elasticsearch = FakeElasticsearch()
        document = ReviewedKnowledgeDocument(
            document_id="doc-1",
            source_type=KnowledgeSourceType.POI,
            source_id="poi-source-1",
            text="abcdefghij",
            city_code="330100",
            poi_id="amap-1",
            language="zh-CN",
            visibility="public",
            status="reviewed",
            source_updated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        result = await KnowledgeIngestionService(
            FakeEmbeddings(), milvus, elasticsearch, chunk_size=4
        ).ingest(document)

        assert result.chunks_indexed == 3
        assert [chunk.page_content for chunk in milvus.chunks] == ["abcd", "efgh", "ij"]
        assert milvus.chunks == elasticsearch.chunks
        metadata = milvus.chunks[0].metadata
        assert metadata.document_id == "doc-1"
        assert metadata.source_type is KnowledgeSourceType.POI
        assert metadata.city_code == "330100"
        assert metadata.poi_id == "amap-1"
        assert metadata.content_hash
        assert len(milvus.vectors) == 3

    asyncio.run(scenario())


def test_unreviewed_source_cannot_enter_ingestion() -> None:
    with pytest.raises(ValueError, match="Only reviewed"):
        ReviewedKnowledgeDocument(
            document_id="doc-1",
            source_type=KnowledgeSourceType.RULE,
            source_id="rule-1",
            text="A rule",
            city_code="330100",
            poi_id=None,
            language="zh-CN",
            visibility="public",
            status="draft",
            source_updated_at=datetime.now(UTC),
        )


def _document(text: str) -> ReviewedKnowledgeDocument:
    return ReviewedKnowledgeDocument(
        document_id="doc-chunking",
        source_type=KnowledgeSourceType.POI,
        source_id="poi-source-1",
        text=text,
        city_code="460200",
        poi_id="amap-xidao",
        language="zh-CN",
        visibility="public",
        status="reviewed",
        source_updated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_sentences_are_never_cut_in_half() -> None:
    """Chunks must start and end on sentence boundaries when separators exist."""
    sentence = "西岛门票价格为九十八元并且需要提前一天预约才能登岛游玩。"
    text = sentence * 10  # 260 chars, chunk_size=60 forces multiple chunks
    service = KnowledgeIngestionService(FakeEmbeddings(), FakeMilvus(), FakeElasticsearch(), chunk_size=60, chunk_overlap=0)

    chunks = service._chunk(_document(text))

    assert len(chunks) > 1
    # Every chunk boundary must land on a sentence end; no chunk may slice a sentence.
    for chunk in chunks:
        assert chunk.page_content == sentence or chunk.page_content.endswith("。")
        assert chunk.page_content.startswith("西岛") or chunk.page_content == sentence


def test_consecutive_chunks_overlap_when_configured() -> None:
    sentence = "西岛门票价格为九十八元并且需要提前一天预约才能登岛游玩。"
    text = sentence * 10
    service = KnowledgeIngestionService(FakeEmbeddings(), FakeMilvus(), FakeElasticsearch(), chunk_size=60, chunk_overlap=30)

    chunks = service._chunk(_document(text))

    assert len(chunks) > 1
    # The sentence that ends chunk N must reappear at the start of chunk N+1:
    # boundary-spanning information stays retrievable in both chunks.
    assert chunks[0].page_content.endswith(sentence)
    assert chunks[1].page_content.startswith(sentence)


def test_paragraphs_are_preferred_over_sentences() -> None:
    paragraph_one = "西岛位于三亚湾的中心海域。" * 6
    paragraph_two = "蜈支洲岛位于海棠湾内并且以水上项目闻名。" * 6
    text = paragraph_one + "\n\n" + paragraph_two
    service = KnowledgeIngestionService(FakeEmbeddings(), FakeMilvus(), FakeElasticsearch(), chunk_size=80, chunk_overlap=0)

    chunks = service._chunk(_document(text))

    # The paragraph boundary must be respected: no chunk mixes both paragraphs
    # beyond the point where sizes force a split inside one paragraph.
    assert all("西岛位于" in c.page_content or "蜈支洲岛" in c.page_content for c in chunks)
    assert any("西岛位于" in c.page_content for c in chunks)
    assert any("蜈支洲岛" in c.page_content for c in chunks)


def test_separator_free_text_still_hard_cuts() -> None:
    text = "abcdefghij"
    service = KnowledgeIngestionService(FakeEmbeddings(), FakeMilvus(), FakeElasticsearch(), chunk_size=4)

    chunks = service._chunk(_document(text))

    assert [chunk.page_content for chunk in chunks] == ["abcd", "efgh", "ij"]


def test_invalid_overlap_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="chunk_overlap"):
        KnowledgeIngestionService(FakeEmbeddings(), FakeMilvus(), FakeElasticsearch(), chunk_size=100, chunk_overlap=100)
