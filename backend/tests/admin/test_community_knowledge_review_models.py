from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import Base
from app.modules.admin.models import CommunityKnowledgeReview
from app.modules.community.models import Post
from app.models.user import User


def test_community_knowledge_review_has_one_post_decision_and_queue_indexes() -> None:
    assert CommunityKnowledgeReview.__table__.c.post_id.foreign_keys
    assert CommunityKnowledgeReview.__table__.c.reviewed_by.foreign_keys
    assert {index.name for index in CommunityKnowledgeReview.__table__.indexes} >= {
        "ix_ckr_status_created",
        "ix_ckr_reviewer_reviewed",
    }

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            review = CommunityKnowledgeReview(post_id="post-0")
            session.add(review)
            session.flush()
            assert review.status == "pending"

            session.add(
                CommunityKnowledgeReview(
                    post_id="post-1",
                    status="approved",
                    reviewed_by="reviewer-1",
                    reviewed_at=datetime(2026, 8, 8, tzinfo=UTC),
                )
            )
            session.commit()

            session.add(CommunityKnowledgeReview(post_id="post-1"))
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_community_knowledge_review_limits_status() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                CommunityKnowledgeReview(post_id="post-2", status="indexing")
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()
