# Itinerary Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe owner-only itinerary deletion and versioned owner/editor day deletion to the saved-plans list and itinerary workspace.

**Architecture:** Add `DELETE /itineraries/{itinerary_id}` as a transactional owner-only aggregate deletion guarded by title confirmation and active companion-plan references. Add `remove_day` to the existing `:operations` state machine so day deletion retains optimistic concurrency, operation idempotency, version history, and current workspace conflict behavior. The Vue pages add explicit confirmation UI and refresh or reselect state after successful deletion.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, Alembic/MySQL, pytest, Vue 3 Composition API, TypeScript, Vite, lucide-vue-next.

## Global Constraints

- Only the itinerary owner can permanently delete an entire itinerary.
- Owner and accepted editor can delete an individual day through `If-Match-Version` and `X-Operation-ID`.
- Deleting the last day leaves an empty itinerary and preserves its current date range.
- Deleting a day removes its events, route segments, and route-calculation jobs, then reorders remaining days.
- Whole-itinerary deletion is rejected while an associated companion plan is `open`, `full`, or `closed`.
- Whole-itinerary deletion requires exact `title_confirmation` and must not partially delete data.
- Do not delete or mutate field-note snapshots when their source itinerary is deleted; nullable source links must be set null by existing foreign-key behavior.
- Preserve current version conflict, idempotency, access-role, and mobile responsive behavior.
- Verify migration lifecycle with `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` if schema changes are required.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/app/modules/itineraries/schemas.py` | Add title-confirmation request and `remove_day` operation literal. |
| `backend/app/modules/itineraries/service.py` | Owner-only aggregate deletion and versioned day removal. |
| `backend/app/modules/itineraries/router.py` | Add DELETE itinerary endpoint and map operation errors. |
| `backend/tests/itineraries/test_deletion.py` | Domain deletion, ownership, companion guard, cascade and remove-day tests. |
| `backend/tests/itineraries/test_router.py` | HTTP auth, confirmation, deletion, and operation response tests. |
| `frontend-c/src/features/itineraries/api.ts` | Typed delete-itinerary API and remove-day operation helper. |
| `frontend-c/src/features/itineraries/pages/ItinerariesPage.vue` | Owner-only list deletion button and title-confirmation dialog. |
| `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue` | Owner plan deletion action, Day Rail delete action, confirmation state, and adjacent-day selection. |
| `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.test.ts` | Delete action and day-selection state tests. |
| `docs/API设计.md` | Document delete and remove-day contracts. |
| `docs/本地验收使用手册.md` | Add deletion acceptance cases. |

## Task 1: Implement Owner Deletion and Versioned Day Removal

**Files:**
- Modify: `backend/app/modules/itineraries/schemas.py`
- Modify: `backend/app/modules/itineraries/service.py`
- Modify: `backend/app/modules/itineraries/router.py`
- Create: `backend/tests/itineraries/test_deletion.py`
- Modify: `backend/tests/itineraries/test_router.py`

**Interfaces:**
- `DELETE /api/v1/itineraries/{itinerary_id}` accepts `{ "title_confirmation": string }` and returns `204`.
- `OperationRequest.operation_type` accepts `remove_day`, with payload `{ "day_id": string }`.
- Existing `OperationResponse` returns `APPLIED`, `VERSION_CONFLICT`, `FORBIDDEN`, or `NOT_FOUND` for day removal.

- [ ] **Step 1: Write failing service tests**

```python
@pytest.mark.anyio
async def test_owner_delete_removes_itinerary_aggregate_and_related_rows(session):
    await service.delete_itinerary(itinerary.id, owner.id, title_confirmation="杭州三日游")
    assert await session.get(Itinerary, itinerary.id) is None
    assert not await session.scalar(select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id))
    assert not await session.scalar(select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id))

@pytest.mark.anyio
async def test_delete_day_removes_events_routes_reorders_and_keeps_empty_itinerary(session):
    result = await service.apply_operation(
        itinerary.id, editor.id, base_version=itinerary.version,
        operation_id="remove-day-1", operation_type="remove_day", payload={"day_id": day.id},
    )
    assert result.code == "APPLIED"
    assert [day["display_order"] for day in result.snapshot["days"]] == [0]

@pytest.mark.anyio
async def test_owner_delete_is_blocked_by_active_companion_plan(session):
    with pytest.raises(ItineraryError, match="COMPANION_PLAN_ACTIVE"):
        await service.delete_itinerary(itinerary.id, owner.id, title_confirmation=itinerary.title)
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/itineraries/test_deletion.py -v`

Expected: FAIL because the deletion service and `remove_day` operation do not exist.

- [ ] **Step 3: Add schemas and owner deletion service**

```python
class DeleteItineraryRequest(BaseModel):
    title_confirmation: str = Field(min_length=1, max_length=160)

class OperationRequest(BaseModel):
    operation_type: Literal["add_day", "remove_day", "add_event", "remove_event", "update_event", "reorder_event", "recalculate_route", "apply_ai_preview"]
```

Implement `ItineraryService.delete_itinerary(itinerary_id, actor_id, title_confirmation) -> None`:

1. Load the itinerary with `with_for_update()`.
2. Return `NOT_FOUND` for missing or non-owner; map non-owner to `FORBIDDEN` at the router.
3. Compare the exact title; raise `TITLE_CONFIRMATION_MISMATCH` before any delete.
4. Query `CompanionRequest` for this itinerary with `status IN ('open', 'full', 'closed')`; raise `COMPANION_PLAN_ACTIVE` if found.
5. Delete route jobs and segments, events, days, trip operations, itinerary versions, collaborators, share tokens, copy-operation rows and the itinerary itself in dependency order. Keep field-note snapshots and let `Post.itinerary_id`/`itinerary_version_id` set null through existing FK behavior.
6. Commit once after all deletes. A failed guard must rollback and leave all rows unchanged.

Use a domain `ItineraryError(code, message)` or the existing itinerary result/error convention consistently; do not return a successful response for a missing or unauthorized itinerary.

- [ ] **Step 4: Add versioned `remove_day` operation**

In `_mutate`, before event-specific logic:

```python
if operation_type == "remove_day":
    day = await self.session.get(ItineraryDay, str(payload.get("day_id", "")))
    if day is None or day.itinerary_id != itinerary.id:
        return OperationResult("NOT_FOUND", itinerary.version)
    await self.session.execute(delete(RouteSegment).where(RouteSegment.day_id == day.id))
    await self.session.execute(delete(RouteCalculationJob).where(RouteCalculationJob.day_id == day.id))
    await self.session.execute(delete(ItineraryEvent).where(ItineraryEvent.day_id == day.id))
    await self.session.delete(day)
    await self.session.flush()
    remaining_days = list((await self.session.scalars(
        select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id).order_by(ItineraryDay.day_date, ItineraryDay.id)
    )).all())
    for order, remaining in enumerate(remaining_days):
        remaining.display_order = order
    if remaining_days:
        itinerary.start_date = min(day.day_date for day in remaining_days)
        itinerary.end_date = max(day.day_date for day in remaining_days)
    return None
```

The existing `apply_operation` then increments the version and records `TripOperation` with `operation_type="remove_day"`, preserving idempotent replay and version conflict behavior. When no days remain, leave `start_date` and `end_date` unchanged.

- [ ] **Step 5: Add HTTP routes and error mapping**

```python
@router.delete("/{itinerary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_itinerary(itinerary_id: str, body: DeleteItineraryRequest, claims: CurrentConsumer, service: Service) -> Response:
    await service.delete_itinerary(itinerary_id, claims.user_id, body.title_confirmation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Map `TITLE_CONFIRMATION_MISMATCH` to `422`, `COMPANION_PLAN_ACTIVE` to `409`, and ownership/missing errors to `403`/`404`. Keep `DELETE /{itinerary_id}/share-tokens/...` route matching intact by placing the exact aggregate route before parameterized subpaths or using FastAPI’s existing route precedence safely.

- [ ] **Step 6: Run backend deletion tests**

Run: `pytest tests/itineraries/test_deletion.py tests/itineraries/test_router.py tests/itineraries/test_versioned_operations.py -v`

Expected: PASS.

- [ ] **Step 7: Commit backend deletion behavior**

```bash
git add backend/app/modules/itineraries/schemas.py backend/app/modules/itineraries/service.py backend/app/modules/itineraries/router.py backend/tests/itineraries/test_deletion.py backend/tests/itineraries/test_router.py
```

## Task 2: Add Safe Consumer Delete Actions

**Files:**
- Modify: `frontend-c/src/features/itineraries/api.ts`
- Modify: `frontend-c/src/features/itineraries/pages/ItinerariesPage.vue`
- Modify: `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue`
- Modify: `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.test.ts`

**Interfaces:**
- `deleteItinerary(itineraryId, titleConfirmation)` sends `{ title_confirmation }` and returns `204`.
- `removeItineraryDay(itineraryId, version, operationId, dayId)` calls the existing operation endpoint.

- [ ] **Step 1: Write failing client/action tests**

```ts
it('sends exact title confirmation for whole itinerary deletion', async () => {
  await deleteItinerary('trip-1', '杭州三日游')
  expect(api.delete).toHaveBeenCalledWith('/itineraries/trip-1', { data: { title_confirmation: '杭州三日游' } })
})

it('removes a day through optimistic operation headers', async () => {
  await removeItineraryDay('trip-1', 3, 'operation-1', 'day-2')
  expect(api.post).toHaveBeenCalledWith('/itineraries/trip-1:operations', {
    operation_type: 'remove_day', payload: { day_id: 'day-2' },
  }, { headers: { 'If-Match-Version': 3, 'X-Operation-ID': 'operation-1' } })
})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `npm run test -- ItineraryWorkspacePage.test.ts`

Expected: FAIL because the API helpers and delete controls do not exist.

- [ ] **Step 3: Implement API helpers and list-page delete flow**

Add typed helpers. In `ItinerariesPage.vue`, render an icon-only `Trash2` button in each owner item, stop click propagation to the `RouterLink`, open a confirmation dialog with the plan title input, and preserve the list while the deletion request is running. On success remove that item from local state and show a specific error on `409`/`422`.

- [ ] **Step 4: Implement workspace day deletion**

Add `removeDayId`, `deletingDay`, and a confirmation dialog. In the Day Rail, add an icon-only trash button within each day entry with `title="删除这一天"` and `aria-label="删除这一天"`. It must not trigger the day selection click.

On confirmation call `removeItineraryDay()` with `store.version`, `crypto.randomUUID()`, and the selected day ID. On `APPLIED`, update the store snapshot/version, select the previous surviving day or index `0`, clear the selected event, and show the empty workspace state when no days remain. On `VERSION_CONFLICT`, preserve the server snapshot and use the existing refresh/conflict state rather than retrying silently.

- [ ] **Step 5: Implement workspace whole-plan deletion**

Add owner-only “删除计划” to the existing more-actions surface. Reuse the same title-confirmation dialog component/state as the list page where practical. On `204`, route to `/itineraries`; on active companion response show “请先结束或取消同行计划后再删除行程。” and keep the workspace open.

- [ ] **Step 6: Run frontend verification**

Run: `npm run test -- ItineraryWorkspacePage.test.ts; npm run typecheck; npm run build`

Expected: PASS.

- [ ] **Step 7: Commit consumer delete controls**

```bash
git add frontend-c/src/features/itineraries/api.ts frontend-c/src/features/itineraries/pages/ItinerariesPage.vue frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.test.ts
```

## Task 3: Documentation and Final Acceptance

**Files:**
- Modify: `docs/API设计.md`
- Modify: `docs/本地验收使用手册.md`
- Test: existing itinerary and frontend suites

- [ ] **Step 1: Document exact delete contracts**

Document owner-only title-confirmed `DELETE /itineraries/{id}`, versioned `remove_day`, companion-plan guard, cascade scope, empty-last-day behavior, and error codes. Add a local acceptance sequence for owner, editor, active companion, last-day deletion, version conflict, desktop, mobile, and keyboard focus.

- [ ] **Step 2: Run final verification**

Run from `backend`:

```bash
pytest tests/itineraries tests/community/test_companion_plans.py -v
```

Run from `frontend-c`:

```bash
npm run test -- --run
npm run typecheck
npm run build
```

Run `git diff --check`. Browser acceptance remains a manual step requiring a logged-in owner/editor session.

## Plan Self-Review

- Whole-plan deletion, title confirmation, ownership, cascade, companion protection: Task 1 and Task 2.
- Versioned day deletion, last-day preservation, date recalculation, route cleanup and conflict handling: Task 1 and Task 2.
- List/workspace controls, responsive confirmation and keyboard actions: Task 2.
- API and local acceptance documentation: Task 3.
- No schema migration is required because all deletion behavior uses existing tables and foreign keys.
