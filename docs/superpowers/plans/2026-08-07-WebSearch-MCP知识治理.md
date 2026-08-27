# WebSearch MCP 知识治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let platform administrators discover web knowledge candidates through Magic WebSearch MCP, review them safely, and send only approved content to the existing official or community RAG ingestion path.

**Architecture:** Add an administrator-only asynchronous web-search job and immutable candidate records in MySQL. A Worker calls an injected `WebSearchProvider`, stores only source metadata and bounded excerpt data, then moves candidates through deterministic review plus an explicit human decision before creating an existing `OfficialKnowledgeSource` or a community-domain source record.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic/MySQL, RabbitMQ Outbox/Worker, httpx MCP client, Vue 3, TypeScript, Element Plus.

## Global Constraints

- WebSearch MCP is administrator-only and must not be called by consumer chat, itinerary generation, or consumer HTTP requests.
- A search result is a candidate, not a travel fact and not a RAG document.
- Store title, bounded excerpt, URL, hostname, published time, fetched time, city, query, target domain, and excerpt hash; never store raw pages or MCP credentials.
- A candidate requires `needs_human_review` and an administrator approval before any RAG ingestion event is emitted.
- `official` candidates create official knowledge only; `community` candidates create community knowledge only. A candidate cannot target user-memory RAG.
- MCP failures create failed jobs and safe summaries; they do not emit knowledge indexing events.
- Use additive MySQL migrations and verify upgrade, downgrade one revision, then upgrade.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/app/integrations/mcp/websearch.py` | Provider protocol, Magic MCP HTTP implementation, unavailable implementation, response validation. |
| `backend/app/modules/admin/models.py` | Web-search job, candidate, and approved external-web knowledge-source persistence mappings. |
| `backend/app/modules/admin/schemas.py` | Admin request/response validation for web-search jobs and candidate decisions. |
| `backend/app/modules/admin/router.py` | Platform-admin APIs to create/list jobs and approve/reject candidates. |
| `backend/app/workers/domain_handlers.py` | Outbox handler that executes a queued search and creates reviewed candidates. |
| `backend/app/core/settings.py` | WebSearch MCP URL/tool/key/timeout settings. |
| `backend/alembic/versions/20260808_0026_websearch_knowledge_candidates.py` | New MySQL tables, constraints, and indexes. |
| `frontend-b/src/features/admin/services/aiOperations.ts` | Typed admin API client additions. |
| `frontend-b/src/features/admin/pages/AiOperationsPage.vue` | Search submission, candidate review queue, approve/reject actions. |
| `backend/tests/admin/` and `backend/tests/workers/` | API, persistence, MCP parsing, and Worker event tests. |
| `frontend-b/src/features/admin/services/aiOperations.test.ts` | Typed API-client tests. |

### Task 1: Persist WebSearch Jobs and Candidates

**Files:**
- Create: `backend/alembic/versions/20260808_0026_websearch_knowledge_candidates.py`
- Modify: `backend/app/modules/admin/models.py`
- Modify: `backend/alembic/env.py`
- Test: `backend/tests/admin/test_websearch_models.py`

**Interfaces:**
- Produces: `WebKnowledgeSearchJob` and `WebKnowledgeCandidate`, consumed by the admin router and Worker.

- [ ] **Step 1: Write failing ORM tests**

```python
def test_web_candidate_requires_public_target_domain_and_human_review_state() -> None:
    candidate = WebKnowledgeCandidate(
        job_id="job-1", title="West Lake", excerpt="Official visitor notice", source_url="https://example.gov/x",
        source_host="example.gov", excerpt_hash="a" * 64, city_code="330100", target_domain="official",
    )
    assert candidate.status == "needs_human_review"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend; pytest tests/admin/test_websearch_models.py -v`

Expected: FAIL because the models do not exist.

- [ ] **Step 3: Add migration and mappings**

Create `web_knowledge_search_jobs` with requester, city, query, target domain (`official` or `community`), status (`queued`, `running`, `succeeded`, `failed`), provider name, error code/message, result count, and timestamps. Create `web_knowledge_candidates` with job FK, title, excerpt, URL, host, optional published timestamp, fetched timestamp, excerpt hash, target domain, status (`needs_human_review`, `approved`, `rejected`, `ingested`, `failed`), review fields, and linked external-web source ID. Create `external_web_knowledge_sources` with candidate FK, target domain, administrator-edited title/body, city, source URL/host, source publication/fetch times, review metadata, and the existing knowledge source lifecycle states. Add unique `(job_id, source_url)`, unique `candidate_id`, and indexes for job, status, target domain, and source status.

- [ ] **Step 4: Verify migration and model test**

Run: `cd backend; alembic upgrade head; alembic downgrade -1; alembic upgrade head; pytest tests/admin/test_websearch_models.py -v`

Expected: migration round trip and test PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic backend/app/modules/admin/models.py backend/tests/admin/test_websearch_models.py
```

### Task 2: Add Safe Magic WebSearch MCP Provider

**Files:**
- Create: `backend/app/integrations/mcp/__init__.py`
- Create: `backend/app/integrations/mcp/websearch.py`
- Modify: `backend/app/core/settings.py`
- Test: `backend/tests/integrations/test_websearch_mcp.py`

**Interfaces:**
- Produces: `WebSearchProvider.search(WebSearchRequest) -> WebSearchResult` and `UnavailableWebSearchProvider`.

- [ ] **Step 1: Write failing provider tests**

```python
@pytest.mark.anyio
async def test_magic_websearch_maps_only_bounded_candidate_fields(httpx_mock) -> None:
    provider = MagicWebSearchProvider(url="https://mcp.example", tool="search", api_key="secret", timeout=15)
    result = await provider.search(WebSearchRequest(query="West Lake", city_code="330100", target_domain="official"))
    assert result.candidates[0].source_host == "travel.example.gov"
    assert len(result.candidates[0].excerpt) <= 4000


@pytest.mark.anyio
async def test_unconfigured_provider_returns_explicit_unavailable_result() -> None:
    result = await UnavailableWebSearchProvider().search(WebSearchRequest("West Lake", "330100", "official"))
    assert result.available is False
    assert result.code == "WEBSEARCH_UNAVAILABLE"
```

- [ ] **Step 2: Run focused tests to verify failure**

Run: `cd backend; pytest tests/integrations/test_websearch_mcp.py -v`

Expected: FAIL because provider types do not exist.

- [ ] **Step 3: Implement provider and settings**

Define frozen request/candidate/result dataclasses and a protocol. The provider sends an MCP tool request with city and query, validates URL as HTTPS, derives host with `urllib.parse.urlparse`, strips control characters, limits title to 300 and excerpt to 4000 characters, parses optional ISO-8601 publication date, and calculates SHA-256 over the normalized excerpt. Add `magic_mcp_websearch_url`, `magic_mcp_websearch_tool`, `magic_mcp_api_key`, and `magic_mcp_timeout_seconds` settings. Missing URL/tool/key yields `UnavailableWebSearchProvider`; never log headers or raw MCP response bodies.

- [ ] **Step 4: Run provider and settings tests**

Run: `cd backend; pytest tests/integrations/test_websearch_mcp.py tests/core/test_settings.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/mcp backend/app/core/settings.py backend/tests/integrations/test_websearch_mcp.py backend/tests/core/test_settings.py
```

### Task 3: Create Admin APIs and Worker Execution

**Files:**
- Modify: `backend/app/modules/admin/schemas.py`
- Modify: `backend/app/modules/admin/router.py`
- Modify: `backend/app/workers/domain_handlers.py`
- Test: `backend/tests/admin/test_websearch_router.py`
- Test: `backend/tests/workers/test_websearch_handler.py`

**Interfaces:**
- Consumes: Tasks 1-2 models and provider.
- Produces: POST/list job APIs, candidate decision API, and `ai.web_knowledge_search_requested` Worker route.

- [ ] **Step 1: Write failing router and Worker tests**

```python
def test_platform_admin_creates_websearch_job_and_outbox_event(client, admin_token) -> None:
    response = client.post("/api/v1/admin/ai/websearch-jobs", json={"city_code": "330100", "query": "West Lake official notice", "target_domain": "official"}, headers=admin_token)
    assert response.status_code == 201
    assert response.json()["status"] == "queued"


@pytest.mark.anyio
async def test_worker_creates_human_review_candidates_without_index_event(session, monkeypatch) -> None:
    monkeypatch.setattr(domain_handlers, "websearch_provider", FakeWebSearchProvider())
    await domain_handlers._search_web_knowledge(session, event_for("job-1"))
    assert candidate.status == "needs_human_review"
    assert await pending_index_events(session) == []
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend; pytest tests/admin/test_websearch_router.py tests/workers/test_websearch_handler.py -v`

Expected: FAIL because routes and handler do not exist.

- [ ] **Step 3: Implement state transitions**

`POST /admin/ai/websearch-jobs` requires platform admin, writes a queued job and Outbox event in one transaction. Worker claims queued jobs, calls the provider outside an uncommitted external transaction, stores candidates as `needs_human_review`, and marks job succeeded; unavailable/invalid provider results mark job failed without candidate indexing.

Add list job/candidate APIs and `PATCH /admin/ai/websearch-candidates/{id}` accepting only `approved` or `rejected`. Approval creates an `ExternalWebKnowledgeSource` from administrator-edited title/body in the candidate's immutable target domain, initially `pending_review`; it does not auto-index. A second existing-style knowledge decision moves the source to `indexing` and emits an Outbox event. The Worker indexes it as `KnowledgeDomain.OFFICIAL` or `KnowledgeDomain.COMMUNITY` according to its stored target domain. Never create a `Post`, and never treat a web candidate as user-authored community content. Reject records the reason. Every decision writes `AdminAction`.

- [ ] **Step 4: Run admin and Worker tests**

Run: `cd backend; pytest tests/admin/test_websearch_router.py tests/workers/test_websearch_handler.py tests/admin/test_ai_knowledge_router.py -v`

Expected: PASS; candidate approval remains distinct from indexing approval.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/admin backend/app/workers/domain_handlers.py backend/tests/admin/test_websearch_router.py backend/tests/workers/test_websearch_handler.py
```

### Task 4: Add Admin WebSearch Operations UI

**Files:**
- Modify: `frontend-b/src/features/admin/services/aiOperations.ts`
- Modify: `frontend-b/src/features/admin/services/aiOperations.test.ts`
- Modify: `frontend-b/src/features/admin/pages/AiOperationsPage.vue`

**Interfaces:**
- Consumes: Admin APIs from Task 3.
- Produces: Platform-admin search submission, candidate inspection, approval, rejection, and safe error states.

- [ ] **Step 1: Write failing API-client tests**

```ts
it('creates a web knowledge search job with city, query, and target domain', async () => {
  await createWebSearchJob('330100', 'West Lake official notice', 'official')
  expect(api.post).toHaveBeenCalledWith('/admin/ai/websearch-jobs', {
    city_code: '330100', query: 'West Lake official notice', target_domain: 'official',
  })
})
```

- [ ] **Step 2: Run frontend test to verify failure**

Run: `cd frontend-b; npm run typecheck; npm run test -- aiOperations.test.ts`

Expected: FAIL because the client function does not exist.

- [ ] **Step 3: Implement bounded review UI**

Add typed job/candidate interfaces and request methods. Add a dialog to submit city, query, and official/community target; show job state and candidates in a dedicated table. Candidate UI displays title, bounded excerpt, host, URL, publication/fetch time, and target domain. Approval opens an edit/confirm dialog; rejection requires reason. Do not render remote HTML, fetch remote URLs in the browser, or expose provider credentials.

- [ ] **Step 4: Run frontend verification**

Run: `cd frontend-b; npm run typecheck; npm run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend-b/src/features/admin/services/aiOperations.ts frontend-b/src/features/admin/services/aiOperations.test.ts frontend-b/src/features/admin/pages/AiOperationsPage.vue
```

### Task 5: Document and Verify the WebSearch Boundary

**Files:**
- Modify: `docs/当前AI工作流说明.md`
- Modify: `docs/AI工作流接入状态.md`
- Test: `backend/tests/integration/test_websearch_knowledge_flow.py`

- [ ] **Step 1: Write failing end-to-end test**

```python
@pytest.mark.anyio
async def test_web_candidate_requires_human_approval_before_rag_indexing(client, worker, admin_token) -> None:
    job = await create_websearch_job(client, admin_token)
    await worker.deliver(job.event)
    assert (await candidates(job.id))[0].status == "needs_human_review"
    assert await retrieval_preview("330100", "candidate fact") == []
```

- [ ] **Step 2: Run test to verify failure before integration wiring**

Run: `cd backend; pytest tests/integration/test_websearch_knowledge_flow.py -v`

Expected: FAIL until Tasks 1-4 are integrated.

- [ ] **Step 3: Document production configuration and human gate**

Document required Magic WebSearch settings, result retention policy, no-consumer-call rule, human approval requirement, and safe failure behavior. Do not include keys, URLs with credentials, or real search results.

- [ ] **Step 4: Run complete verification**

Run: `cd backend; pytest tests/admin tests/workers/test_websearch_handler.py tests/integrations/test_websearch_mcp.py tests/integration/test_websearch_knowledge_flow.py -v`

Run: `cd frontend-b; npm run typecheck; npm run build`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add docs backend/tests/integration/test_websearch_knowledge_flow.py
```

## Self-Review

- Covers administrator-only WebSearch, candidate-only storage, deterministic provider validation, Worker execution, human review, domain routing, UI, audit, and integration acceptance.
- Excludes consumer web search, direct RAG insertion, raw-page persistence, and unreviewed fact output as required.
- All provider, model, API, Worker, and UI interfaces are introduced before later tasks consume them.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-07-WebSearch-MCP知识治理.md`.
