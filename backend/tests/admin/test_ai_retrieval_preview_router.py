from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.modules.admin.router as admin_router
from app.core.database import get_session
from app.main import create_app
from app.modules.ai_rag.catalog import DomainRetrievalRequest
from app.modules.ai_rag.types import Citation, KnowledgeDomain, KnowledgeSourceType, RagContextItem, RagResult, RagStatus
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


class FakeRetrievalCatalog:
    def __init__(self, result: RagResult) -> None:
        self.result = result
        self.requests: list[DomainRetrievalRequest] = []

    async def retrieve(self, request: DomainRetrievalRequest) -> RagResult:
        self.requests.append(request)
        return self.result


class FakeRetrievalRuntime:
    def __init__(self, result: RagResult) -> None:
        self.catalog = FakeRetrievalCatalog(result)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _available_result() -> RagResult:
    citation = Citation(
        document_id="document-1",
        chunk_id="document-1:0:abc",
        source_type=KnowledgeSourceType.RULE,
        source_id="source-1",
        city_code="330100",
        poi_id=None,
        source_updated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    return RagResult(
        RagStatus.AVAILABLE,
        contexts=(RagContextItem("Leave time between lakeside stops.", citation, 0.91),),
        message=None,
    )


def _client(monkeypatch: pytest.MonkeyPatch, runtime_factory, auth: AuthService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth

    async def unexpected_session():
        raise AssertionError("retrieval preview must not open a business database session")

    app.dependency_overrides[get_session] = unexpected_session
    monkeypatch.setattr(admin_router, "open_domain_retrieval_runtime", runtime_factory)
    return TestClient(app)


def test_platform_admin_can_run_read_only_retrieval_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = AuthService(InMemoryTTLStore(), secret="admin-retrieval-preview-test-secret")
    runtime = FakeRetrievalRuntime(_available_result())

    async def open_runtime():
        return runtime

    token = auth.create_access_token(user_id="admin-1", audience="admin", roles=["platform_admin"])
    with _client(monkeypatch, open_runtime, auth) as client:
        response = client.post(
            "/api/v1/admin/ai/retrieval-preview",
            headers={"Authorization": f"Bearer {token}"},
            json={"city_code": "330100", "query": "west lake walking"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "available",
        "message": None,
        "contexts": [
            {
                "rank": 1,
                "score": 0.91,
                "content": "Leave time between lakeside stops.",
                "citation": {
                    "document_id": "document-1",
                    "chunk_id": "document-1:0:abc",
                    "source_type": "rule",
                    "source_id": "source-1",
                    "city_code": "330100",
                    "poi_id": None,
                    "source_updated_at": "2026-08-01T00:00:00Z",
                },
            }
        ],
    }
    assert runtime.catalog.requests == [
        DomainRetrievalRequest(
            domain=KnowledgeDomain.OFFICIAL,
            query="west lake walking",
            city_code="330100",
        )
    ]
    assert runtime.closed


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (RagStatus.NO_RESULTS, "No reviewed travel knowledge matched this city and query."),
        (RagStatus.CLARIFICATION_REQUIRED, "Available sources are too low-confidence to use as travel facts."),
        (RagStatus.UNAVAILABLE, "Travel knowledge is unavailable."),
    ],
)
def test_retrieval_statuses_are_returned_as_success_responses(
    monkeypatch: pytest.MonkeyPatch, status: RagStatus, message: str
) -> None:
    auth = AuthService(InMemoryTTLStore(), secret=f"admin-retrieval-{status.value}")
    runtime = FakeRetrievalRuntime(RagResult(status, message=message))

    async def open_runtime():
        return runtime

    token = auth.create_access_token(user_id="admin-2", audience="admin", roles=["platform_admin"])
    with _client(monkeypatch, open_runtime, auth) as client:
        response = client.post(
            "/api/v1/admin/ai/retrieval-preview",
            headers={"Authorization": f"Bearer {token}"},
            json={"city_code": "330100", "query": "west lake"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": status.value, "message": message, "contexts": []}
    assert runtime.closed


def test_retrieval_preview_requires_platform_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = AuthService(InMemoryTTLStore(), secret="admin-retrieval-auth-test-secret")
    called = False

    async def open_runtime():
        nonlocal called
        called = True
        raise AssertionError("unauthorized retrieval must not construct a runtime")

    consumer_token = auth.create_access_token(user_id="user-1", audience="consumer", roles=["user"])
    with _client(monkeypatch, open_runtime, auth) as client:
        response = client.post(
            "/api/v1/admin/ai/retrieval-preview",
            headers={"Authorization": f"Bearer {consumer_token}"},
            json={"city_code": "330100", "query": "west lake"},
        )

    assert response.status_code == 403
    assert not called


def test_retrieval_runtime_fault_returns_safe_503(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = AuthService(InMemoryTTLStore(), secret="admin-retrieval-fault-test-secret")

    async def open_runtime():
        raise RuntimeError("private connector credentials must not be exposed")

    token = auth.create_access_token(user_id="admin-3", audience="admin", roles=["platform_admin"])
    with _client(monkeypatch, open_runtime, auth) as client:
        response = client.post(
            "/api/v1/admin/ai/retrieval-preview",
            headers={"Authorization": f"Bearer {token}"},
            json={"city_code": "330100", "query": "west lake"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "AI_RETRIEVAL_UNAVAILABLE"
    assert response.json()["message"] == "AI retrieval is unavailable for this probe."
    assert "private connector credentials" not in response.text
