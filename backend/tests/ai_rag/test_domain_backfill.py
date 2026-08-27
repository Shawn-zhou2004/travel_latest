from __future__ import annotations

from datetime import UTC, datetime

from app.modules.admin.models import OfficialKnowledgeSource
from app.modules.ai_rag.backfill import ApprovedCommunityPosts, DomainBackfillService
from app.modules.ai_rag.types import AuthorityLevel, KnowledgeDomain, KnowledgeSourceType
from app.modules.community.models import Post


NOW = datetime(2026, 8, 7, tzinfo=UTC)
OFFICIAL_ID = "00000000-0000-4000-8000-000000000001"
POST_ID = "00000000-0000-4000-8000-000000000002"


def _official_source(*, source_id: str = OFFICIAL_ID) -> OfficialKnowledgeSource:
    return OfficialKnowledgeSource(
        id=source_id,
        source_type="rule",
        title="Official entry rule",
        body_text="Bring a valid passport.",
        city_code="330100",
        poi_id=None,
        language="en",
        status="indexed",
        reviewed_at=NOW,
        updated_at=NOW,
    )


def _post() -> Post:
    return Post(
        id=POST_ID,
        author_id="00000000-0000-4000-8000-000000000003",
        title="Local breakfast note",
        body_text="Arrive before eight.",
        city_code="330100",
        status="published",
        published_at=NOW,
        updated_at=NOW,
    )


def test_selects_domain_specific_documents_from_reviewed_sources() -> None:
    documents = DomainBackfillService().select_documents(
        official_sources=(_official_source(),),
        approved_community_posts=ApprovedCommunityPosts(posts=(_post(),)),
    )

    assert [(document.document_id, document.knowledge_domain) for document in documents] == [
        (OFFICIAL_ID, KnowledgeDomain.OFFICIAL),
        (POST_ID, KnowledgeDomain.COMMUNITY),
    ]
    official, community = documents
    assert official.source_type is KnowledgeSourceType.RULE
    assert official.authority_level is AuthorityLevel.OFFICIAL
    assert community.source_type is KnowledgeSourceType.COMMUNITY
    assert community.authority_level is AuthorityLevel.COMMUNITY


def test_selection_is_idempotent_for_repeated_sources() -> None:
    source = _official_source()

    documents = DomainBackfillService().select_documents(official_sources=(source, source))

    assert len(documents) == 1
    assert documents[0].document_id == OFFICIAL_ID


def test_published_posts_are_not_included_without_explicit_approval_input() -> None:
    documents = DomainBackfillService().select_documents(
        official_sources=(_official_source(),),
    )

    assert [document.knowledge_domain for document in documents] == [KnowledgeDomain.OFFICIAL]
