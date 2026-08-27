# Reviewed POI Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a city-scoped POI candidate pool where user-confirmed live discoveries await administrator review, approved tagged attractions rank ahead of live web fallback in AI itinerary planning.

**Architecture:** Live web and AMap remain discovery-only and task-local until a user confirms a generated preview. Confirmation emits an Outbox event that lets the Worker validate and upsert candidate POIs into MySQL; administrators approve, tag, and weight candidates before they become public recommendation records and existing official RAG knowledge sources. Planning reads active approved candidates by city and requested tags, ranks them by internal signals, verifies them with AMap, then falls back to reviewed RAG and live web only when needed.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic/MySQL, RabbitMQ Outbox Worker, PostgreSQL LangGraph preview storage, Vue 3, Pinia, Element Plus, Vitest, pytest.

## Global Constraints

- MySQL is the source of truth for candidate lifecycle, tags, ranking signals, and administrator decisions.
- Only `platform_admin` can approve, reject, retire, tag, or weight POI candidates.
- A user selection never automatically becomes official knowledge; it becomes a `pending_review` candidate only after preview confirmation.
- Persist only AMap-verified POI metadata and approved tags; never persist raw web pages, private prompts, or MCP payloads.
- Allowed initial tags are exactly: `经典必玩`, `自然风光`, `历史古建`, `文艺展览`, `吃吃喝喝`, `逛街购物`, `拍照出片`, `citywalk`, `小众探索`.
- Internal ranking uses `admin_weight`, `confirmed_itinerary_count`, and `discovery_count`; do not scrape, store, or claim third-party ratings.
- New planning candidates must be AMap-verified, city-matched, unique, and attraction-category POIs before they enter a preview.
- Keep live MCP/AMap as a last fallback when approved candidates and reviewed RAG cannot supply two unique verified POIs per requested day.
- Schema changes require an additive Alembic migration and `upgrade -> downgrade -1 -> upgrade` verification against configured MySQL.

---

## File Structure

- `backend/app/modules/admin/models.py`: owns `PoiCandidate` lifecycle, verified AMap snapshot, tags, internal metrics, review fields, and official knowledge linkage.
- `backend/alembic/versions/20260811_0036_poi_candidates.py`: creates `poi_candidates`, city/status/ranking indexes, and lifecycle constraints.
- `backend/app/modules/admin/schemas.py`: candidate response, list filters, and guarded approval/rejection request schemas.
- `backend/app/modules/admin/router.py`: platform-admin candidate queue/list/decision endpoints, audit recording, and existing official-source handoff.
- `backend/app/workers/domain_handlers.py`: records user-confirmed preview POIs into candidate pool through a new Outbox event handler.
- `backend/app/modules/ai_workflows/contracts.py`: adds request preference tags and an approved planning candidate retrieval protocol.
- `backend/app/modules/ai_workflows/workflow.py`: combines ranked approved candidates with reviewed RAG before using live fallback.
- `backend/app/modules/ai_workflows/runtime.py`: supplies candidate retrieval implementation without exposing unapproved records.
- `backend/app/modules/itineraries/service.py`: emits the candidate discovery Outbox event only after an AI preview is successfully applied.
- `frontend-b/src/features/admin/services/poiCandidates.ts`: typed admin API client.
- `frontend-b/src/features/admin/pages/PoiCandidatesPage.vue`: queue for review, tags, ranking weight, approval, rejection, and retirement.
- `frontend-b/src/router/index.ts` and `frontend-b/src/App.vue`: admin-only navigation to the candidate queue.
- `backend/tests/admin/test_poi_candidates_router.py`, `backend/tests/workers/test_poi_candidate_discovery.py`, `backend/tests/ai_workflows/test_approved_candidates.py`: lifecycle, authorization, ranking, and fallback coverage.
- `frontend-b/src/features/admin/services/poiCandidates.test.ts`, `frontend-b/src/features/admin/pages/PoiCandidatesPage.test.ts`, `frontend-b/src/router/index.test.ts`: client, UI, and access coverage.
- `docs/API设计.md`, `docs/本地验收使用手册.md`, `docs/错误复盘记录.md`: contract, administrator workflow, and known-boundary documentation.

### Task 1: Add Candidate POI Schema And Migration

**Files:**
- Modify: `backend/app/modules/admin/models.py`
- Create: `backend/alembic/versions/20260811_0036_poi_candidates.py`
- Modify: `backend/alembic/env.py`
- Test: `backend/tests/admin/test_poi_candidate_models.py`

**Interfaces:**
- Produces `PoiCandidate` with `status`, `tags`, `admin_weight`, `discovery_count`, `confirmed_itinerary_count`, and `official_knowledge_source_id`.
- Consumes AMap `poi_id`, name, address, location, `type_name`, and city `adcode` from Worker validation.

- [ ] **Step 1: Write failing model tests**

```python
candidate = PoiCandidate(
    poi_id="B03830048T", city_code="460200", name="天涯海角游览区",
    address="三亚市", longitude=109.2, latitude=18.3, amap_type="风景名胜",
)
assert candidate.status == "pending_review"
assert candidate.tags == []
assert candidate.discovery_count == 1
assert candidate.confirmed_itinerary_count == 0
assert candidate.admin_weight == 0
```

- [ ] **Step 2: Run the model test to verify it fails**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\admin\test_poi_candidate_models.py -q`

Expected: FAIL because `PoiCandidate` does not exist.

- [ ] **Step 3: Add the model and migration**

Create `poi_candidates` with UUID primary key, unique `poi_id`, city/status and city/status/ranking indexes, allowed lifecycle `pending_review|approved|rejected|retired`, JSON `tags`, non-negative counts/weight, optional review fields, and optional `official_knowledge_source_id` foreign key. Use `UTCDateTime`, `TimestampMixin`, and MySQL-compatible JSON/index declarations matching other admin models.

- [ ] **Step 4: Verify migration lifecycle**

Run:

```powershell
cd backend
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
```

Expected: migration head is `20260811_0036` and all commands succeed.

- [ ] **Step 5: Run model tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\admin\test_poi_candidate_models.py -q`

Expected: PASS.

### Task 2: Persist Confirmed Live Discoveries As Candidate POIs

**Files:**
- Modify: `backend/app/modules/itineraries/service.py`
- Modify: `backend/app/workers/domain_handlers.py`
- Test: `backend/tests/workers/test_poi_candidate_discovery.py`

**Interfaces:**
- Consumes an applied AI preview ID and owner ID from an Outbox event.
- Produces upserted `PoiCandidate` records with `discovery_count += 1` and `confirmed_itinerary_count += 1`.

- [ ] **Step 1: Write a failing Worker test**

```python
await _record_confirmed_preview_candidates(session, event)
candidate = await session.scalar(select(PoiCandidate).where(PoiCandidate.poi_id == "poi-1"))
assert candidate.status == "pending_review"
assert candidate.discovery_count == 1
assert candidate.confirmed_itinerary_count == 1
```

Include cases for duplicate POIs across dates, a non-attraction AMap result, and a second confirmed use of the same POI.

- [ ] **Step 2: Run the Worker test to verify it fails**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\workers\test_poi_candidate_discovery.py -q`

Expected: FAIL because no handler/event exists.

- [ ] **Step 3: Emit a post-confirmation Outbox event**

After `apply_ai_preview` succeeds in `ItineraryService.apply_operation`, emit `ai.confirmed_preview_poi_discovery_requested` with only `preview_id`, `generation_job_id`, `user_id`, and itinerary ID. Do not include prompt text, citations, web URLs, or private preview payloads in the event.

- [ ] **Step 4: Implement Worker upsert**

The Worker loads the owner-scoped PostgreSQL preview, deduplicates POI IDs, verifies each with AMap, discards non-attraction or wrong-city POIs, and upserts `PoiCandidate`. Preserve approved tags, status, admin weight, and official-source linkage when refreshing an existing candidate; only increment internal counts and update verified metadata.

- [ ] **Step 5: Register and verify event handling**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\workers\test_poi_candidate_discovery.py tests\events\test_generation_consumer.py -q`

Expected: PASS; duplicate delivery does not double-count because the existing processed-event guard applies.

### Task 3: Build Admin Candidate Review API

**Files:**
- Modify: `backend/app/modules/admin/schemas.py`
- Modify: `backend/app/modules/admin/router.py`
- Test: `backend/tests/admin/test_poi_candidates_router.py`

**Interfaces:**
- `GET /api/v1/admin/ai/poi-candidates?status=pending_review&city_code=460200`
- `PATCH /api/v1/admin/ai/poi-candidates/{candidate_id}` with `{status, tags, admin_weight, reason}`.
- Approval creates one pending `OfficialKnowledgeSource(source_type="poi")`; it is indexed only through the existing official-source review endpoint.

- [ ] **Step 1: Write failing route tests**

```python
response = client.patch(
    f"/api/v1/admin/ai/poi-candidates/{candidate_id}",
    json={"status": "approved", "tags": ["经典必玩", "自然风光"], "admin_weight": 20, "reason": "城市地标，适合首次到访。"},
    headers=admin_headers,
)
assert response.status_code == 200
assert response.json()["status"] == "approved"
assert response.json()["official_knowledge_source_id"]
```

Cover non-admin `403`, missing rejection reason `422`, duplicate tags `422`, out-of-range weight `422`, second decision `409`, and no automatic index event on candidate approval.

- [ ] **Step 2: Run the route test to verify it fails**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\admin\test_poi_candidates_router.py -q`

Expected: FAIL with `404` or missing schema.

- [ ] **Step 3: Implement schemas and routes**

Use explicit Pydantic response models. Restrict tags to the nine global tags, deduplicate tags, require at least one tag on approval, require reason on rejection/retirement, and limit `admin_weight` to `0..100`. Approval creates a `pending_review` `OfficialKnowledgeSource` with a concise verified POI description only; it does not store raw web text or auto-index.

- [ ] **Step 4: Record audit actions**

Call existing `_record` for all decisions, including status, tags, weight, and official-source ID. Do not expose review actor internals in consumer-facing APIs.

- [ ] **Step 5: Run route tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\admin\test_poi_candidates_router.py tests\admin\test_ai_workflow_health_router.py -q`

Expected: PASS.

### Task 4: Retrieve And Rank Approved Candidates Before Live Fallback

**Files:**
- Modify: `backend/app/modules/ai_workflows/contracts.py`
- Modify: `backend/app/modules/ai_workflows/runtime.py`
- Modify: `backend/app/modules/ai_workflows/workflow.py`
- Modify: `backend/app/workers/domain_handlers.py`
- Test: `backend/tests/ai_workflows/test_approved_candidates.py`

**Interfaces:**
- `GenerationRequest.preference_tags: tuple[str, ...]`
- `ApprovedPlanningCandidateRetriever.retrieve(request) -> tuple[VerifiedPlanningCandidate, ...]`
- Ranking order: `admin_weight DESC`, `confirmed_itinerary_count DESC`, `discovery_count DESC`, `updated_at DESC`, `poi_id ASC`.

- [ ] **Step 1: Write failing ranking tests**

```python
result = await retriever.retrieve(request_with_classic_tag)
assert [candidate.poi_id for candidate in result[:3]] == ["landmark", "popular-beach", "museum"]
assert all(candidate.source.source_type == "approved_poi" for candidate in result)
```

Cover city isolation, tag intersection, retired/rejected exclusion, AMap verification failure exclusion, duplicate citation/POI suppression, and fallback to live sources only when fewer than `2 * trip_days` candidates remain.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\ai_workflows\test_approved_candidates.py -q`

Expected: FAIL because approved candidate retrieval is absent.

- [ ] **Step 3: Add request tags and injected retrieval dependency**

Pass normalized preference tags from `GenerationJob.request_json` into `GenerationRequest`. Keep the dependency behind a protocol so workflow tests can inject fakes; do not query MySQL directly from LangGraph node code.

- [ ] **Step 4: Implement candidate selection and citations**

Query only `approved` candidate rows within the request city and with at least one requested tag. If no preference tags are supplied, use all approved attraction candidates for that city. AMap-verify each selected POI at use time, construct `approved_poi` citations using candidate ID and review timestamp, then merge them before reviewed RAG/live candidates.

- [ ] **Step 5: Preserve current safety behavior**

Keep a minimum of two verified unique POIs per day. Do not allow approved candidates to bypass city validation, attraction checks, deduplication, schema validation, or itinerary constraints.

- [ ] **Step 6: Run workflow regression tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\ai_workflows\test_approved_candidates.py tests\ai_workflows\test_workflow.py tests\workers\test_generation_handler.py -q`

Expected: PASS.

### Task 5: Add The Administrator Candidate Queue

**Files:**
- Create: `frontend-b/src/features/admin/services/poiCandidates.ts`
- Create: `frontend-b/src/features/admin/services/poiCandidates.test.ts`
- Create: `frontend-b/src/features/admin/pages/PoiCandidatesPage.vue`
- Create: `frontend-b/src/features/admin/pages/PoiCandidatesPage.test.ts`
- Modify: `frontend-b/src/router/index.ts`
- Modify: `frontend-b/src/router/index.test.ts`
- Modify: `frontend-b/src/App.vue`

**Interfaces:**
- Lists `/admin/ai/poi-candidates` with `pending_review` selected initially.
- Reviews a candidate with tags, integer `admin_weight`, and decision reason.

- [ ] **Step 1: Write failing service and page tests**

```ts
expect(api.get).toHaveBeenCalledWith('/admin/ai/poi-candidates', {
  params: { status: 'pending_review', limit: 50 },
})
expect(api.patch).toHaveBeenCalledWith(`/admin/ai/poi-candidates/${id}`, {
  status: 'approved', tags: ['经典必玩'], admin_weight: 20, reason: '城市地标',
})
```

Test that approval is disabled without a tag, rejection requires a reason, a successful decision reloads the queue, and the route rejects non-admin sessions.

- [ ] **Step 2: Run frontend tests to verify they fail**

Run: `cd frontend-b; npm test -- --run src/features/admin/services/poiCandidates.test.ts src/features/admin/pages/PoiCandidatesPage.test.ts src/router/index.test.ts`

Expected: FAIL because the service/page/route do not exist.

- [ ] **Step 3: Implement typed client and review page**

Use the established Element Plus table/dialog patterns. Show name, AMap category, city code, internal metrics, candidate state, tags, and verified time. Present the nine tags as toggles, an integer weight input, and explicit approve/reject/retire actions. Do not show user IDs, prompts, raw web source URLs, or private itinerary content.

- [ ] **Step 4: Wire navigation and authorization**

Add an admin-only `景点候选审核` route and navigation entry near existing AI operations. Preserve the established admin layout and mobile behavior.

- [ ] **Step 5: Run focused frontend tests and typecheck**

Run:

```powershell
cd frontend-b
npm test -- --run src/features/admin/services/poiCandidates.test.ts src/features/admin/pages/PoiCandidatesPage.test.ts src/router/index.test.ts
npm run typecheck
```

Expected: PASS.

### Task 6: Document, Verify, And Exercise The Full Lifecycle

**Files:**
- Modify: `docs/API设计.md`
- Modify: `docs/本地验收使用手册.md`
- Modify: `docs/错误复盘记录.md`

- [ ] **Step 1: Document API and data boundaries**

Describe candidate lifecycle, admin-only decision routes, internal ranking inputs, and the rule that confirmed discoveries are pending review rather than automatically official.

- [ ] **Step 2: Document acceptance flow**

Add this concrete manual flow: generate and confirm a live-backed itinerary; wait for Worker; review candidate in admin UI; approve with `经典必玩`; review/index created official source; create a matching plan; verify approved candidate citations precede `live_web` fallback.

- [ ] **Step 3: Run migration verification**

Run:

```powershell
cd backend
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
```

Expected: all commands succeed against MySQL.

- [ ] **Step 4: Run backend and frontend verification**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/admin/test_poi_candidate_models.py tests/admin/test_poi_candidates_router.py tests/workers/test_poi_candidate_discovery.py tests/ai_workflows/test_approved_candidates.py -q
cd ..\frontend-b
npm run typecheck
npm run build
```

Expected: all checks pass.

- [ ] **Step 5: Record test evidence**

Append the final migration, test, and manual three-POI ranking result to `docs/错误复盘记录.md` only if an implementation issue required diagnosis. Do not log credentials or user content.

## Self-Review

- Spec coverage: candidate discovery after user confirmation is Task 2; review/tags are Task 3 and Task 5; internal popularity ranking is Task 4; approved official-source handoff is Task 3; live fallback remains constrained in Task 4; migration, documentation, and verification are Tasks 1 and 6.
- Intentional scope exclusions: no full-national POI import, third-party rating ingestion, raw web-page storage, automatic official approval, or consumer-facing candidate moderation.
- Type consistency: `PoiCandidate` is the persisted source for review and ranking; `VerifiedPlanningCandidate` remains the workflow-safe verified object; `GenerationRequest.preference_tags` carries the selected consumer tags; `approved_poi` citations distinguish curated candidates from `live_web` and existing reviewed RAG citations.
