from __future__ import annotations

import pytest

from app.modules.ai_rag.catalog import DomainRetrievalRequest
from app.modules.ai_rag.types import KnowledgeDomain, RetrievalFilter


def test_user_memory_domain_requires_user_id() -> None:
    with pytest.raises(ValueError, match="user_id"):
        DomainRetrievalRequest(
            domain=KnowledgeDomain.USER_MEMORY,
            query="quiet hotels",
            city_code="330100",
        )


def test_private_retrieval_requires_private_visibility() -> None:
    with pytest.raises(ValueError, match="private"):
        RetrievalFilter(
            city_code="330100",
            knowledge_domain=KnowledgeDomain.USER_MEMORY,
            user_id="user-1",
        )
