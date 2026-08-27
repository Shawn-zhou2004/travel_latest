# Smart Trip Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the consumer planning form with destination autocomplete, structured preferences, manual itinerary creation, and source-controlled smart planning that can use per-job MCP search results.

**Architecture:** The consumer chooses a destination result resolved by the backend to a canonical city code. Smart planning persists that selection as a generation-job snapshot, uses reviewed RAG knowledge first, and uses bounded MCP result metadata only as temporary per-job evidence when reviewed candidates are insufficient. Every planned stop must be resolved and verified by AMap before the existing immutable-preview and versioned confirmation path can use it. Manual planning stays synchronous and creates only an empty itinerary date skeleton.

**Tech Stack:** Vue 3, TypeScript, Pinia, Vite, FastAPI, Pydantic v2, SQLAlchemy async, Alembic/MySQL, PostgreSQL/asyncpg for AI previews, RabbitMQ Outbox Worker, AMap Web Service API, Magic MCP WebSearch, Milvus, Elasticsearch, pytest, Vitest.

## Global Constraints

- Do not require consumers to know or enter a city administrative code, RAG, MCP, or POI ID.
- A destination must be selected from a backend-provided result before either planning action is enabled.
- Destination autocomplete must show a primary name and full hierarchical address, support mouse and keyboard selection, debounce calls, and ignore stale responses.
- Date ranges are consecutive `1-7` days; past start dates and end dates before start dates are invalid.
- The selectable preference values are exactly `经典必玩`、`吃吃喝喝`、`小众探索`、`拍照出片`、`逛街购物`、`citywalk`、`自然风光`、`文艺展览`、`历史古建`; allow at most three.
- Free-form supplemental text is optional and is not used as a substitute for structured preference tags.
- Manual planning must not call MCP, RAG, LLM, or Worker services.
- Reviewed knowledge is always searched before live MCP sources.
- Live MCP data is task-local evidence only: it must not be inserted into Milvus, Elasticsearch, or long-term knowledge tables without the separate existing admin review workflow.
- The Worker must never fetch or store raw web pages. It may use bounded HTTPS MCP title, excerpt, and source URL metadata only.
- A planned stop must have a source citation, an AMap-verified non-empty `poi_id`, target-city membership, and coordinates. Never invent POIs or facts.
- Smart planning targets three verified stops per day; two are permitted only with a preview explanation; fewer than two stops on any day is `no_result`.
- Preview confirmation must remain owner-scoped, immutable before confirmation, version-checked, and idempotent.
- New external calls need bounded timeout, candidate count, and task-level attempt limits. Never log tokens, DSNs, raw page bodies, or presigned URLs.
- Preserve existing unrelated worktree changes and use `apply_patch` for manual edits.

---

## File Structure

- Create `backend/app/modules/destinations/router.py`: consumer-authenticated destination autocomplete endpoint.
- Create `backend/app/modules/destinations/service.py`: AMap-derived result normalization, city-code normalization, deterministic result ranking, and request validation.
- Create `backend/app/modules/destinations/schemas.py`: public destination search request/response Pydantic models.
- Create `backend/tests/destinations/test_router.py`: auth, response contract, ambiguity, ranking, and error tests.
- Modify `backend/app/modules/maps/service.py`: add a focused administrative/destination search method and normalize AMap district/place responses into one internal result shape.
- Modify `backend/app/api/router.py`: include the destinations router.
- Modify `backend/app/modules/itineraries/schemas.py`, `router.py`, `service.py`: add a manual-plan command which creates an empty date skeleton using the selected destination display snapshot.
- Modify `backend/app/modules/ai_workflows/schemas.py`, `service.py`, `models.py`, and relevant Alembic revision: persist destination display snapshot and preference tags in generation request JSON; expose new task progress stages safely.
- Create `backend/app/modules/ai_workflows/live_sources.py`: task-local source candidate, verified candidate, and citation conversion types; no persistence in knowledge indexes.
- Modify `backend/app/integrations/mcp/websearch.py`: add a bounded user-planning search adapter API that reuses validated MCP metadata parsing but does not use the admin-only `.gov.cn` eligibility policy.
- Modify `backend/app/modules/ai_workflows/runtime.py`, `workflow.py`, `contracts.py`: retrieve reviewed candidates, fall back to live source candidates, AMap-resolve them, and plan only from verified candidates.
- Modify `backend/app/workers/domain_handlers.py`: pass preference and destination snapshots to the workflow, emit safe progress changes, and map insufficient verified candidates to `no_result`.
- Modify `backend/app/modules/ai_memory/postgres.py` and `schemas.py`: preserve source type and task-local citation attributes in immutable previews without storing raw page content.
- Modify `frontend-c/src/features/itineraries/aiPlanningApi.ts`: destination, preferences, manual plan, updated job stage, and source-type contracts.
- Modify `frontend-c/src/features/itineraries/stores/aiPlanning.ts`: submit structured requests, expose state for manual planning and task outcomes.
- Replace `frontend-c/src/features/itineraries/pages/PlanPage.vue`: destination combobox, dates, preference tags, optional prompt, manual and smart actions, accessible status, and preview source labels.
- Create/update `frontend-c/src/features/itineraries/pages/PlanPage.test.ts` and `frontend-c/src/features/itineraries/aiPlanningApi.test.ts`: interaction, validation, stale autocomplete, manual path, and API contract tests.
- Modify `docs/API设计.md`, `docs/本地验收使用手册.md`, and `docs/项目进度与完成度总结.md`: document endpoints, real-time source boundaries, status meanings, and local acceptance steps.

## Task 1: Destination Autocomplete Contract and AMap Normalization

**Files:**
- Create: `backend/app/modules/destinations/schemas.py`
- Create: `backend/app/modules/destinations/service.py`
- Create: `backend/app/modules/destinations/router.py`
- Modify: `backend/app/modules/maps/service.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/destinations/test_router.py`
- Test: `backend/tests/maps/test_service.py`

**Interfaces:**
- Consumes: `AMapService.search_destinations(query: str, *, limit: int = 8) -> list[DestinationMatch]`.
- Produces: `GET /api/v1/destinations?query={query}` returning `DestinationSearchResponse(items: list[DestinationResponse])`.
- Produces: `DestinationResponse(id: str, name: str, display_address: str, city_code: str, kind: Literal["city", "district", "scenic_area"])`.

- [ ] **Step 1: Write failing AMap normalization tests**

```python
@pytest.mark.anyio
async def test_search_destinations_normalizes_city_and_district_and_ranks_exact_name_first() -> None:
    service = AMapService(api_key="key", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    results = await service.search_destinations("长沙")
    assert [(item.name, item.display_address, item.city_code) for item in results] == [
        ("长沙市", "中国 · 湖南省 · 长沙市", "430100"),
        ("长沙县", "中国 · 湖南省 · 长沙市 · 长沙县", "430100"),
        ("长春市", "中国 · 吉林省 · 长春市", "220100"),
    ]
```

- [ ] **Step 2: Run the failing map test**

Run: `python -m pytest tests/maps/test_service.py::test_search_destinations_normalizes_city_and_district_and_ranks_exact_name_first -q`

Expected: FAIL because `AMapService.search_destinations` does not exist.

- [ ] **Step 3: Implement `DestinationMatch` and `AMapService.search_destinations`**

```python
@dataclass(frozen=True)
class DestinationMatch:
    id: str
    name: str
    display_address: str
    city_code: str
    kind: Literal["city", "district", "scenic_area"]

async def search_destinations(self, query: str, *, limit: int = 8) -> list[DestinationMatch]:
    payload = await self._get("https://restapi.amap.com/v5/config/district", {
        "key": self.api_key, "keywords": query, "subdistrict": 0, "extensions": "base",
    })
    return _rank_destination_matches(_destination_matches(payload), query)[:limit]
```

Normalize district results to their prefecture city code. Where AMap returns a district adcode, resolve its city-level code by calling the same district endpoint with the selected adcode and walking the returned hierarchy; cache nothing across requests in this first version. Build `display_address` only from returned country/province/city/district fields and reject incomplete items without a canonical city code.

- [ ] **Step 4: Write failing authenticated router tests**

```python
def test_destination_search_requires_consumer_auth(client: TestClient) -> None:
    response = client.get("/api/v1/destinations", params={"query": "长沙"})
    assert response.status_code == 401

def test_destination_search_returns_public_normalized_results(client: TestClient, consumer_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/destinations", params={"query": "长沙"}, headers=consumer_headers)
    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "id": "430100", "name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市",
        "city_code": "430100", "kind": "city",
    }
```

- [ ] **Step 5: Implement the destination module and include router**

```python
router = APIRouter(prefix="/destinations", tags=["destinations"])

@router.get("", response_model=DestinationSearchResponse)
async def search_destinations(
    claims: CurrentConsumer,
    query: Annotated[str, Query(min_length=1, max_length=80)],
    service: DestinationService = Depends(get_destination_service),
) -> DestinationSearchResponse:
    del claims
    return DestinationSearchResponse(items=await service.search(query))
```

`DestinationService.search()` must trim input, reject blank-after-trim input, map unavailable AMap results to `503` with `DESTINATION_SEARCH_UNAVAILABLE`, and return an empty `items` array for a valid query with no matches. Include this router in `app/api/router.py`.

- [ ] **Step 6: Run focused tests**

Run: `python -m pytest tests/maps/test_service.py tests/destinations/test_router.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the destination contract**

```bash
git add backend/app/modules/destinations backend/app/modules/maps/service.py backend/app/api/router.py backend/tests/destinations backend/tests/maps/test_service.py
git commit -m "feat: add consumer destination search"
```

## Task 2: Manual Date-Skeleton Planning

**Files:**
- Modify: `backend/app/modules/itineraries/schemas.py`
- Modify: `backend/app/modules/itineraries/router.py`
- Modify: `backend/app/modules/itineraries/service.py`
- Test: `backend/tests/itineraries/test_router.py`
- Test: `backend/tests/itineraries/test_services.py`

**Interfaces:**
- Consumes: `SelectedDestination(name, display_address, city_code)` from the validated request body.
- Produces: `POST /api/v1/itineraries:manual-plan` with `ManualPlanCreateRequest` and `201 ItineraryResponse`.
- Produces: initial itinerary snapshot with every requested date and no events.

- [ ] **Step 1: Write the failing service test**

```python
@pytest.mark.anyio
async def test_create_manual_plan_creates_all_dates_without_events(session: AsyncSession, user: User) -> None:
    itinerary = await ItineraryService(session).create_manual_plan(
        user.id, title="长沙三日游", start_date=date(2026, 8, 10), end_date=date(2026, 8, 12),
        destination={"name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100"},
    )
    assert [day["date"] for day in (await ItineraryService(session).get_snapshot(itinerary))["days"]] == [
        "2026-08-10", "2026-08-11", "2026-08-12"
    ]
    assert all(day["events"] == [] for day in (await ItineraryService(session).get_snapshot(itinerary))["days"])
```

- [ ] **Step 2: Run the failing service test**

Run: `python -m pytest tests/itineraries/test_services.py::test_create_manual_plan_creates_all_dates_without_events -q`

Expected: FAIL because `create_manual_plan` does not exist.

- [ ] **Step 3: Add request schema and minimal service method**

```python
class SelectedDestination(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    display_address: str = Field(min_length=1, max_length=300)
    city_code: str = Field(pattern=r"^\d{6}$")

class ManualPlanCreateRequest(BaseModel):
    destination: SelectedDestination
    start_date: date
    end_date: date
    title: str | None = Field(default=None, max_length=160)

async def create_manual_plan(
    self, owner_id: str, *, title: str | None, start_date: date, end_date: date,
    destination: dict[str, str],
) -> Itinerary:
    itinerary = await self.create_itinerary(owner_id, title=title or f"{destination['name']}行程", start_date=start_date, end_date=end_date)
    await self._ensure_days(itinerary)
    await self.session.commit()
    return itinerary
```

Store the destination display snapshot only in the initial itinerary version snapshot metadata, not in a new global table. Reuse existing version creation and authorization logic. Do not call `AMapService`, Outbox, or AI runtime.

- [ ] **Step 4: Write router behavior tests**

```python
def test_manual_plan_rejects_invalid_date_range(client: TestClient, consumer_headers: dict[str, str]) -> None:
    response = client.post("/api/v1/itineraries:manual-plan", headers=consumer_headers, json={
        "destination": {"name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100"},
        "start_date": "2026-08-12", "end_date": "2026-08-10",
    })
    assert response.status_code == 422
```

- [ ] **Step 5: Implement `POST /itineraries:manual-plan`**

Use `CurrentConsumer`, `ItineraryService.create_manual_plan`, and `ItineraryResponse`. Return `201`. Ensure the normal create endpoint remains unchanged for callers that already use it.

- [ ] **Step 6: Run itinerary tests**

Run: `python -m pytest tests/itineraries/test_services.py tests/itineraries/test_router.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the manual planning path**

```bash
git add backend/app/modules/itineraries backend/tests/itineraries
git commit -m "feat: add manual itinerary planning"
```

## Task 3: Persist Structured Smart-Planning Input and Progress

**Files:**
- Modify: `backend/app/modules/ai_workflows/schemas.py`
- Modify: `backend/app/modules/ai_workflows/service.py`
- Modify: `backend/app/modules/ai_workflows/models.py`
- Create: `backend/alembic/versions/<revision>_generation_destination_snapshot.py`
- Modify: `backend/app/modules/ai_workflows/router.py`
- Test: `backend/tests/ai_workflows/test_job_service.py`
- Test: `backend/tests/ai_workflows/test_router.py`

**Interfaces:**
- Consumes: `GenerationJobCreate(destination: SelectedDestination, preference_tags: list[PreferenceTag], prompt: str = "")`.
- Produces: generation `request_json` keys `destination`, `city_code`, `preference_tags`, `prompt`, `start_date`, and `end_date`.
- Produces: `GenerationJobStatus` stages `resolving_destination`, `retrieving_reviewed_sources`, `searching_live_sources`, `verifying_pois`, `planning`, `validating`.

- [ ] **Step 1: Write failing input-schema and service snapshot tests**

```python
def test_generation_job_accepts_selected_destination_and_three_preferences() -> None:
    body = GenerationJobCreate.model_validate({
        "destination": {"name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100"},
        "start_date": "2026-08-10", "end_date": "2026-08-12",
        "preference_tags": ["吃吃喝喝", "citywalk", "历史古建"], "prompt": "有老人同行",
    })
    assert body.city_code == "430100"

@pytest.mark.anyio
async def test_generation_job_stores_destination_and_preference_snapshot(
    session: AsyncSession, consumer: User,
) -> None:
    job = await service.create(user.id, "key", body)
    assert job.request_json["destination"]["display_address"] == "中国 · 湖南省 · 长沙市"
    assert job.request_json["preference_tags"] == ["吃吃喝喝", "citywalk", "历史古建"]
```

- [ ] **Step 2: Run the failing job tests**

Run: `python -m pytest tests/ai_workflows/test_job_service.py -q`

Expected: FAIL because `destination` and preference validation do not exist.

- [ ] **Step 3: Implement schema compatibility and persisted snapshot**

Keep `city_code` as an internal derived property for existing workflow code, but make it absent from the public create body. Define `PreferenceTag` as a `Literal` of the nine approved values and validate `max_length=3`, no duplicate tags. Permit an empty prompt; normalize it to `""`. Do not add a separate table unless the existing JSON request snapshot cannot persist the selected destination.

Only add an Alembic revision if a new model column is actually needed after inspecting the current `GenerationJob` schema. If no model field is necessary, omit the migration and document that `request_json` is the immutable snapshot store.

- [ ] **Step 4: Add safe progress transition method tests**

```python
@pytest.mark.anyio
async def test_generation_job_accepts_live_search_progress_before_planning(
    session: AsyncSession, consumer: User,
) -> None:
    await service.mark_progress(job.id, status="searching_live_sources", progress=45)
    await session.refresh(job)
    assert (job.status, job.progress) == ("searching_live_sources", 45)
```

- [ ] **Step 5: Implement status enum and guarded transition method**

Expand model/schema literals and the active-status sets consistently. `mark_progress` must only advance an active job owned by the current worker attempt and must never overwrite terminal outcome/error fields. Do not expose raw MCP query or source content in the job response.

- [ ] **Step 6: Run AI job tests**

Run: `python -m pytest tests/ai_workflows/test_job_service.py tests/ai_workflows/test_router.py -q`

Expected: PASS.

- [ ] **Step 7: Commit structured smart-plan input**

```bash
git add backend/app/modules/ai_workflows backend/tests/ai_workflows backend/alembic/versions
git commit -m "feat: persist structured smart planning input"
```

## Task 4: Task-Local Live Source Candidates and Verified POI Pipeline

**Files:**
- Create: `backend/app/modules/ai_workflows/live_sources.py`
- Modify: `backend/app/integrations/mcp/websearch.py`
- Modify: `backend/app/modules/ai_workflows/contracts.py`
- Modify: `backend/app/modules/ai_workflows/runtime.py`
- Modify: `backend/app/modules/ai_workflows/workflow.py`
- Test: `backend/tests/ai_workflows/test_live_sources.py`
- Test: `backend/tests/integrations/test_websearch_provider.py`
- Test: `backend/tests/ai_workflows/test_workflow.py`

**Interfaces:**
- Produces: `LiveSourceCandidate(name_hint: str, source_url: str, source_host: str, excerpt: str, source_type: Literal["live_web"])`.
- Produces: `VerifiedPlanningCandidate(poi_id: str, poi_name: str, city_code: str, longitude: float, latitude: float, source: Citation)`.
- Consumes: `WebSearchProvider.search(query, limit)` and `AMapService.search_pois(name_hint, city_code)`.
- Produces: `LiveSourceRetriever.retrieve(request) -> tuple[LiveSourceCandidate, ...]` with `MAX_LIVE_SOURCE_CANDIDATES = 12`.

- [ ] **Step 1: Write failing live-source filtering tests**

```python
@pytest.mark.anyio
async def test_live_source_pipeline_keeps_only_same_city_verified_unique_pois() -> None:
    candidates = await resolver.resolve(
        request=_request(city_code="430100"),
        sources=(
            _source("岳麓山", "https://example.cn/yuelu", "长沙岳麓山游览信息"),
            _source("岳麓山", "https://example.cn/duplicate", "长沙岳麓山步行建议"),
            _source("橘子洲", "https://example.cn/juzizhou", "长沙橘子洲游览信息"),
        ),
    )
    assert [item.poi_id for item in candidates] == ["poi-yuelu", "poi-juzizhou"]
```

- [ ] **Step 2: Run the failing live-source test**

Run: `python -m pytest tests/ai_workflows/test_live_sources.py::test_live_source_pipeline_keeps_only_same_city_verified_unique_pois -q`

Expected: FAIL because the task-local source module does not exist.

- [ ] **Step 3: Implement source types and resolver**

```python
MAX_LIVE_SOURCE_CANDIDATES = 12

class LiveSourceResolver:
    async def resolve(
        self, request: GenerationRequest, sources: tuple[LiveSourceCandidate, ...]
    ) -> tuple[VerifiedPlanningCandidate, ...]:
        verified: list[VerifiedPlanningCandidate] = []
        seen_poi_ids: set[str] = set()
        for source in sources[:MAX_LIVE_SOURCE_CANDIDATES]:
            matches = await self._maps.search_pois(source.name_hint, request.city_code)
            poi = next((item for item in matches if _city_code_matches(request.city_code, item.adcode or "")), None)
            if poi is None or poi.id in seen_poi_ids:
                continue
            seen_poi_ids.add(poi.id)
            verified.append(VerifiedPlanningCandidate.from_poi(poi, source))
        return tuple(verified)
```

Use only `title` and `excerpt` from `WebSearchCandidate` to derive a bounded `name_hint`; do not fetch `source_url`. Reject non-HTTPS URLs, duplicate URL hashes, blank hints, missing excerpts, missing city code, and cross-city AMap matches.

- [ ] **Step 4: Write failing fallback policy tests**

```python
@pytest.mark.anyio
async def test_workflow_does_not_call_live_search_when_reviewed_candidates_cover_all_days(
    reviewed_dependencies: GenerationDependencies, request: GenerationRequest,
) -> None:
    await workflow.run(_request(days=3))
    assert live_source_retriever.calls == []

@pytest.mark.anyio
async def test_workflow_uses_live_sources_when_reviewed_candidates_cannot_fill_two_stops_per_day(
    fallback_dependencies: GenerationDependencies, request: GenerationRequest,
) -> None:
    state = await workflow.run(_request(days=3))
    assert state.live_source_used is True
    assert all(len(day.activities) >= 2 for day in state.verified_draft.days)
```

- [ ] **Step 5: Integrate reviewed-first then live fallback in workflow**

Extend `GenerationDependencies` with `live_source_retriever` and `live_source_resolver`. Convert reviewed RAG citations into planning candidates where their metadata supports an existing POI ID; count distinct verified candidates. If this does not cover `2 * requested_day_count`, call the live retriever once. Carry only verified candidates into the structured generator prompt and validation stage.

Update prompt instructions so the generator receives a `verified_candidates` array and must select only those `poi_id` values. Keep the existing JSON repair retry. Reject generated stops outside that candidate set before AMap verification.

- [ ] **Step 6: Implement insufficient-data outcome**

Raise a typed constraint/availability result with the safe message `"Not enough verified places were found for this trip."` if any day cannot contain two verified stops. Map it in the worker to `no_result`, not `unavailable`. Preserve dependency failures as `unavailable`.

- [ ] **Step 7: Run focused source and workflow tests**

Run: `python -m pytest tests/integrations/test_websearch_provider.py tests/ai_workflows/test_live_sources.py tests/ai_workflows/test_workflow.py -q`

Expected: PASS.

- [ ] **Step 8: Commit live retrieval and verification**

```bash
git add backend/app/integrations/mcp/websearch.py backend/app/modules/ai_workflows backend/tests/integrations/test_websearch_provider.py backend/tests/ai_workflows
git commit -m "feat: add verified live planning sources"
```

## Task 5: Worker Progress, Preview Source Labels, and Authorization

**Files:**
- Modify: `backend/app/workers/domain_handlers.py`
- Modify: `backend/app/modules/ai_memory/postgres.py`
- Modify: `backend/app/modules/ai_workflows/schemas.py`
- Modify: `backend/app/modules/ai_workflows/router.py`
- Test: `backend/tests/workers/test_generation_handler.py`
- Test: `backend/tests/ai_workflows/test_router.py`
- Test: `backend/tests/ai_memory/test_postgres.py`

**Interfaces:**
- Consumes: `WorkflowState.source_summary` with only source type, URL host, title/excerpt-derived citation text, and verified POI association.
- Produces: preview citations with `source_type` values `reviewed_knowledge` or `live_web`.
- Produces: safe worker status updates `retrieving_reviewed_sources`, `searching_live_sources`, `verifying_pois`, `planning`, `validating`.

- [ ] **Step 1: Write failing worker progress tests**

```python
@pytest.mark.anyio
async def test_generation_handler_records_live_search_and_poi_verification_progress(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await domain_handlers._run_generation(session, _event(job.id))
    await session.refresh(job)
    assert captured_statuses == ["retrieving_reviewed_sources", "searching_live_sources", "verifying_pois", "planning", "validating"]
```

- [ ] **Step 2: Run the failing worker test**

Run: `python -m pytest tests/workers/test_generation_handler.py::test_generation_handler_records_live_search_and_poi_verification_progress -q`

Expected: FAIL because these progress statuses are not emitted.

- [ ] **Step 3: Implement worker progress callbacks and error mapping**

Pass a status callback into the workflow or record status immediately before each top-level phase. The callback must never contain search query text, raw excerpts, URLs with query parameters, or model content. `Not enough verified places` is terminal `succeeded/no_result`; MCP/AMap failures remain retryable `DependencyUnavailable`; invalid model JSON remains terminal `failed/unavailable/INVALID_DRAFT_SCHEMA` after the existing repair attempts.

- [ ] **Step 4: Write failing preview citation persistence tests**

```python
@pytest.mark.anyio
async def test_preview_persists_live_source_type_without_raw_page_body(repository: AIMemoryRepository) -> None:
    preview = await repository.save_preview(_request(), _verified_draft(), (_live_citation(),), ())
    stored = await repository.get_preview("user-1", preview.preview_id)
    assert stored["citations"][0]["source_type"] == "live_web"
    assert "raw_html" not in stored["citations"][0]
```

- [ ] **Step 5: Implement citation serialization and preview response labels**

Reuse existing preview citation tables if `source_type` is already stored. Add a schema field only if source type cannot be returned. Do not persist raw external body columns. Ensure the existing owner-scoped `get_preview` behavior is unchanged and add a second-user denial test covering a preview with `live_web` citation.

- [ ] **Step 6: Run worker, preview, and authorization tests**

Run: `python -m pytest tests/workers/test_generation_handler.py tests/ai_workflows/test_router.py tests/ai_memory/test_postgres.py -q`

Expected: PASS.

- [ ] **Step 7: Commit worker and preview source behavior**

```bash
git add backend/app/workers/domain_handlers.py backend/app/modules/ai_memory/postgres.py backend/app/modules/ai_workflows backend/tests/workers backend/tests/ai_workflows backend/tests/ai_memory
git commit -m "feat: expose safe smart planning progress"
```

## Task 6: Consumer API Client and Planning Store

**Files:**
- Modify: `frontend-c/src/features/itineraries/aiPlanningApi.ts`
- Modify: `frontend-c/src/features/itineraries/stores/aiPlanning.ts`
- Create: `frontend-c/src/features/itineraries/destinationsApi.ts`
- Test: `frontend-c/src/features/itineraries/aiPlanningApi.test.ts`
- Test: `frontend-c/src/features/itineraries/stores/aiPlanning.test.ts`
- Test: `frontend-c/src/features/itineraries/destinationsApi.test.ts`

**Interfaces:**
- Produces: `searchDestinations(query: string): Promise<DestinationOption[]>`.
- Produces: `createManualPlan(request: ManualPlanRequest): Promise<ItinerarySummary>`.
- Consumes: `AiPlanningRequest { destination, start_date, end_date, preference_tags, prompt }`.
- Produces: `GenerationJobStatus` including the new source-resolution progress stages.

- [ ] **Step 1: Write failing API serialization tests**

```ts
it('posts the selected destination and preference tags instead of a user-entered city code', async () => {
  await createGenerationJob({
    destination: { id: '430100', name: '长沙市', display_address: '中国 · 湖南省 · 长沙市', city_code: '430100', kind: 'city' },
    start_date: '2026-08-10', end_date: '2026-08-12', preference_tags: ['吃吃喝喝', 'citywalk'], prompt: '',
  }, 'operation-1')
  expect(api.post).toHaveBeenCalledWith('/generation-jobs', expect.objectContaining({ preference_tags: ['吃吃喝喝', 'citywalk'] }), expect.anything())
})
```

- [ ] **Step 2: Run failing frontend API tests**

Run: `npm test -- --pool=threads --poolOptions.threads.singleThread=true src/features/itineraries/aiPlanningApi.test.ts src/features/itineraries/destinationsApi.test.ts`

Expected: FAIL because destination and manual-plan clients do not exist.

- [ ] **Step 3: Implement exact TypeScript contracts**

```ts
export interface DestinationOption { id: string; name: string; display_address: string; city_code: string; kind: 'city' | 'district' | 'scenic_area' }
export interface SmartPlanRequest { destination: DestinationOption; start_date: string; end_date: string; preference_tags: PreferenceTag[]; prompt: string }
export type PreferenceTag = '经典必玩' | '吃吃喝喝' | '小众探索' | '拍照出片' | '逛街购物' | 'citywalk' | '自然风光' | '文艺展览' | '历史古建'
```

Keep operation IDs generated client-side as existing code does. Add `createManualPlan` without involving the AI store polling path. Add user-facing labels for all new server statuses.

- [ ] **Step 4: Write failing store behavior tests**

```ts
it('keeps no-result distinct from an unavailable live search dependency', async () => {
  getJob.mockResolvedValue(job({ status: 'succeeded', outcome: 'no_result', message: 'Not enough verified places were found for this trip.' }))
  await useAiPlanningStore().submit(request)
  expect(useAiPlanningStore().state).toBe('no_result')
})
```

- [ ] **Step 5: Implement store message mapping and manual-plan isolation**

Map safe insufficient-place results to Chinese copy explaining users may adjust preferences or plan manually. Preserve `INVALID_DRAFT_SCHEMA` wording. Ensure manual planning does not change `job`, `preview`, polling timer, or the retry state.

- [ ] **Step 6: Run frontend API and store tests**

Run: `npm test -- --pool=threads --poolOptions.threads.singleThread=true src/features/itineraries/aiPlanningApi.test.ts src/features/itineraries/destinationsApi.test.ts src/features/itineraries/stores/aiPlanning.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit consumer planning contracts**

```bash
git add frontend-c/src/features/itineraries/aiPlanningApi.ts frontend-c/src/features/itineraries/destinationsApi.ts frontend-c/src/features/itineraries/stores frontend-c/src/features/itineraries/*.test.ts
git commit -m "feat: add consumer smart planning contracts"
```

## Task 7: Replace the Plan Screen With an Accessible Consumer Flow

**Files:**
- Modify: `frontend-c/src/features/itineraries/pages/PlanPage.vue`
- Create: `frontend-c/src/features/itineraries/pages/PlanPage.test.ts`
- Modify: `frontend-c/src/router/index.ts` only if manual-plan navigation needs a new route parameter helper.

**Interfaces:**
- Consumes: `searchDestinations`, `createManualPlan`, and `useAiPlanningStore().submit` from Task 6.
- Produces: navigation to `/itineraries/{id}` after manual-plan creation or preview confirmation.

- [ ] **Step 1: Write failing component tests for autocomplete and validation**

```ts
it('requires selecting a destination option rather than submitting typed text', async () => {
  await user.type(screen.getByLabelText('目的地'), '长沙')
  await user.click(screen.getByRole('button', { name: '智能规划' }))
  expect(screen.getByRole('alert')).toHaveTextContent('请从搜索结果中选择目的地')
})

it('selects a destination by keyboard and submits no more than three preferences', async () => {
  await user.type(screen.getByLabelText('目的地'), '长沙')
  await user.keyboard('{ArrowDown}{Enter}')
  expect(screen.getByDisplayValue('长沙市')).toBeVisible()
  expect(screen.getByText('中国 · 湖南省 · 长沙市')).toBeVisible()
})
```

- [ ] **Step 2: Run the failing component tests**

Run: `npm test -- --pool=threads --poolOptions.threads.singleThread=true src/features/itineraries/pages/PlanPage.test.ts`

Expected: FAIL because the page currently accepts administrative code text and uses templates.

- [ ] **Step 3: Replace the planning form state and markup**

Use a `<input role="combobox">` with `aria-controls`, `aria-expanded`, active option tracking, and a `role="listbox"` results panel. Debounce only after at least one non-whitespace character. Increment a request sequence before every search and ignore a response whose sequence no longer matches. Clear selected destination whenever the input value diverges from its selected `name`.

Render the selected tags as toggle buttons with `aria-pressed`; prevent a fourth selection with specific inline copy. Keep optional supplemental text separate. Delete the template rail and the obsolete fixed prompt defaults. Keep the existing parsing mode untouched unless it conflicts with layout.

Render distinct `手动规划` and `智能规划` buttons. The manual button calls `createManualPlan` and pushes the returned itinerary URL. The smart button calls the planning store only when a selected destination and valid dates exist. Disable both only while their own request is active; do not make manual planning depend on AI job state.

- [ ] **Step 4: Add component tests for stale search, manual planning, and source labels**

```ts
it('ignores an older destination response after a newer query completes', async () => {
  // Resolve the "长" request after the "长沙" request and assert only the latter remains visible.
})

it('creates a manual date skeleton without calling the generation endpoint', async () => {
  await user.click(screen.getByRole('button', { name: '手动规划' }))
  expect(createManualPlan).toHaveBeenCalledOnce()
  expect(createGenerationJob).not.toHaveBeenCalled()
})

it('labels live web citations in an AI preview', async () => {
  expect(screen.getByText('本次实时网络资料')).toBeVisible()
})
```

- [ ] **Step 5: Implement responsive styling and focus states**

Keep the established field-paper visual language. Make destination options a single unframed list directly below the input, not nested cards. On screens below `500px`, stack dates and make both planning actions full-width without clipping long Chinese labels. Provide `:focus-visible` treatment for options, tags, and actions. Respect `prefers-reduced-motion` for progress and dropdown transitions.

- [ ] **Step 6: Run component, typecheck, and production build**

Run: `npm test -- --pool=threads --poolOptions.threads.singleThread=true src/features/itineraries/pages/PlanPage.test.ts`

Expected: PASS.

Run: `npm run typecheck`

Expected: PASS.

Run: `npm run build`

Expected: PASS.

- [ ] **Step 7: Commit the planning UI**

```bash
git add frontend-c/src/features/itineraries/pages/PlanPage.vue frontend-c/src/features/itineraries/pages/PlanPage.test.ts frontend-c/src/router/index.ts
git commit -m "feat: redesign consumer planning entry"
```

## Task 8: Documentation and End-to-End Acceptance

**Files:**
- Modify: `docs/API设计.md`
- Modify: `docs/本地验收使用手册.md`
- Modify: `docs/项目进度与完成度总结.md`
- Test: relevant backend and frontend suites from Tasks 1-7

**Interfaces:**
- Documents: destination autocomplete, manual-plan endpoint, structured smart-plan input, task-local live source boundary, stage names, and acceptance procedures.

- [ ] **Step 1: Update API contract documentation**

Add request and response examples for:

```text
GET /api/v1/destinations?query=长沙
POST /api/v1/itineraries:manual-plan
POST /api/v1/generation-jobs
```

Document that live MCP citations are per-preview only, sources are not auto-indexed, and all stops require AMap verification.

- [ ] **Step 2: Add local acceptance instructions**

Include these browser cases:

```text
1. Type 长沙; confirm 长沙市 / 中国 · 湖南省 · 长沙市 is selectable.
2. Verify typing 长沙 without selection blocks planning.
3. Select 2026-08-10 to 2026-08-12 and up to three preferences.
4. Run 手动规划 with AI services stopped; verify three empty days open in the workspace.
5. Run 智能规划 with reviewed sources available; verify preview citations and confirm behavior.
6. Run 智能规划 with reviewed sources insufficient but MCP available; verify searching_live_sources and live-web labels.
7. Verify fewer than two verified daily places gives no_result and no itinerary write.
8. Verify a second consumer cannot read task, preview, or citations.
```

- [ ] **Step 3: Run backend full suite**

Run: `python -m pytest -q`

Expected: PASS; record skips and non-failing dependency warnings.

- [ ] **Step 4: Run frontend full suite, typecheck, and build**

Run: `npm test -- --pool=threads --poolOptions.threads.singleThread=true`

Expected: PASS.

Run: `npm run typecheck`

Expected: PASS.

Run: `npm run build`

Expected: PASS.

- [ ] **Step 5: Run browser acceptance**

Start the consumer development server if it is not already listening. Use the browser acceptance workflow to test the eight cases above at desktop and mobile viewports. Capture only non-sensitive screenshots; do not include credentials, full task IDs, source query parameters, or presigned URLs.

- [ ] **Step 6: Run final diff validation and commit documentation**

Run: `git diff --check`

Expected: PASS with no whitespace errors.

```bash
git add docs/API设计.md docs/本地验收使用手册.md docs/项目进度与完成度总结.md
git commit -m "docs: document smart trip planning"
```

## Plan Self-Review

- Spec coverage: Tasks 1 and 7 cover autocomplete, hierarchical result display, debounce, keyboard support, tags, dates, and responsive UI. Task 2 covers AI-independent manual planning. Tasks 3-5 cover structured inputs, reviewed-first retrieval, bounded task-local MCP fallback, POI verification, source labels, error mapping, ownership, and immutable previews. Task 8 covers docs and acceptance.
- Placeholder scan: no `TODO`, `TBD`, deferred implementation, or unspecified error-handling steps remain.
- Type consistency: `DestinationOption`/`SelectedDestination` contain the same public fields; `city_code` stays a derived internal workflow field; `LiveSourceCandidate` is explicitly distinct from reviewed `Citation`; `VerifiedPlanningCandidate` is the only candidate type sent to the generator.
