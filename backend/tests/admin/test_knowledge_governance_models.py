from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import Base
from app.modules.admin.models import OfficialKnowledgeSource


def test_official_knowledge_source_has_governance_metadata() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            source = OfficialKnowledgeSource(
                source_type="rule",
                title="Visitor rules",
                body_text="Keep to marked paths.",
            )
            session.add(source)
            session.flush()

            assert source.knowledge_domain == "official"
            assert source.source_version == "1"
            assert source.next_review_at is None
            assert source.supersedes_document_id is None
    finally:
        engine.dispose()

    assert OfficialKnowledgeSource.__table__.c.supersedes_document_id.foreign_keys
    assert {index.name for index in OfficialKnowledgeSource.__table__.indexes} >= {
        "ix_oks_domain_status_city",
        "ix_oks_next_review",
        "ix_oks_supersedes",
    }


def test_official_knowledge_source_limits_knowledge_domain() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                OfficialKnowledgeSource(
                    source_type="rule",
                    knowledge_domain="user_memory",
                    title="Visitor rules",
                    body_text="Keep to marked paths.",
                    next_review_at=datetime(2026, 8, 9, tzinfo=UTC),
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()
