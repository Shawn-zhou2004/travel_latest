import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import Base
from app.modules.admin.models import (
    ExternalWebKnowledgeSource,
    WebKnowledgeCandidate,
    WebKnowledgeSearchJob,
)


def test_web_candidate_requires_public_target_domain_and_human_review_state() -> None:
    candidate = WebKnowledgeCandidate(
        job_id="job-1",
        title="West Lake",
        excerpt="Official visitor notice",
        source_url="https://example.gov/x",
        source_host="example.gov",
        excerpt_hash="a" * 64,
        city_code="330100",
        target_domain="official",
    )

    assert candidate.status == "needs_human_review"

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                WebKnowledgeCandidate(
                    job_id="job-2",
                    title="West Lake",
                    excerpt="Official visitor notice",
                    source_url="https://example.gov/y",
                    source_host="example.gov",
                    excerpt_hash="b" * 64,
                    city_code="330100",
                    target_domain="user_memory",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_web_search_job_requires_public_target_domain_and_known_status() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                WebKnowledgeSearchJob(
                    requested_by="requester-1",
                    city_code="330100",
                    query="West Lake official notice",
                    target_domain="internal",
                    status="complete",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_web_candidate_persists_metadata_only_with_one_linked_external_source() -> None:
    candidate_columns = WebKnowledgeCandidate.__table__.c
    source_columns = ExternalWebKnowledgeSource.__table__.c

    assert "body_text" not in candidate_columns
    assert "raw_html" not in candidate_columns
    assert candidate_columns.external_web_source_id.foreign_keys
    assert source_columns.candidate_id.foreign_keys
    assert any(
        constraint.name == "uq_web_knowledge_candidates_job_source_url_hash"
        for constraint in WebKnowledgeCandidate.__table__.constraints
    )
    assert any(
        constraint.name == "uq_external_web_knowledge_sources_candidate_id"
        for constraint in ExternalWebKnowledgeSource.__table__.constraints
    )
