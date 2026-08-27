from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.modules.ai_rag.types import (
    AuthorityLevel,
    KnowledgeDomain,
    KnowledgeSourceType,
    ReviewedKnowledgeDocument,
)

if TYPE_CHECKING:
    from app.modules.admin.models import OfficialKnowledgeSource
    from app.modules.community.models import Post


@dataclass(frozen=True)
class ApprovedCommunityPosts:
    """Posts explicitly approved by the owning knowledge-review workflow."""

    posts: tuple[Post, ...]


class DomainBackfillService:
    """Build domain-scoped RAG documents from caller-supplied reviewed sources."""

    def select_documents(
        self,
        *,
        official_sources: Iterable[OfficialKnowledgeSource] = (),
        approved_community_posts: ApprovedCommunityPosts | None = None,
    ) -> tuple[ReviewedKnowledgeDocument, ...]:
        documents = {
            document.document_id: document
            for document in self._official_documents(official_sources)
        }
        if approved_community_posts is not None:
            documents.update(
                {
                    document.document_id: document
                    for document in self._community_documents(approved_community_posts.posts)
                }
            )
        return tuple(documents[document_id] for document_id in sorted(documents))

    @staticmethod
    def _official_documents(
        sources: Iterable[OfficialKnowledgeSource],
    ) -> Iterable[ReviewedKnowledgeDocument]:
        for source in sources:
            # Rejected and inactive records retain reviewed_at but are not approved for indexing.
            if source.reviewed_at is None or source.status != "indexed":
                continue
            yield ReviewedKnowledgeDocument(
                document_id=source.id,
                source_type=KnowledgeSourceType(source.source_type),
                source_id=source.id,
                text=f"{source.title}\n\n{source.body_text}",
                city_code=source.city_code,
                poi_id=source.poi_id,
                language=source.language,
                visibility="public",
                status="reviewed",
                source_updated_at=source.updated_at,
                knowledge_domain=KnowledgeDomain.OFFICIAL,
                authority_level=AuthorityLevel.OFFICIAL,
                reviewed_at=source.reviewed_at,
            )

    @staticmethod
    def _community_documents(posts: Iterable[Post]) -> Iterable[ReviewedKnowledgeDocument]:
        for post in posts:
            if post.status != "published":
                continue
            yield ReviewedKnowledgeDocument(
                document_id=post.id,
                source_type=KnowledgeSourceType.COMMUNITY,
                source_id=post.id,
                text=f"{post.title}\n\n{post.body_text}",
                city_code=post.city_code,
                poi_id=None,
                language="zh-CN",
                visibility="public",
                status="reviewed",
                source_updated_at=post.updated_at,
                knowledge_domain=KnowledgeDomain.COMMUNITY,
                authority_level=AuthorityLevel.COMMUNITY,
                reviewed_at=post.published_at,
            )
