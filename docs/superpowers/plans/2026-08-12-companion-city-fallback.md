# Companion City Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users publish a companion plan from an older itinerary without city metadata by choosing a destination city name through the existing controlled destination search, while keeping city codes internal.

**Architecture:** The backend continues to prefer city data projected from the current itinerary snapshot. `CompanionPlanCreate.city_code` becomes an optional, validated fallback used only when no trusted itinerary city exists. The publish page resolves and displays a destination name through the existing `/destinations` selector only when automatic detection fails; it sends the selected internal city code without exposing it in the UI.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, pytest, Vue 3 Composition API, TypeScript, Vite, existing destination search API.

## Global Constraints

- Users never see, type, or infer administrative city codes.
- The server always prefers city data from the persisted itinerary version over the submitted fallback city code.
- The fallback is allowed only when the current itinerary lacks a usable city; it updates only the new companion plan metadata and never changes the itinerary.
- The city selector must reuse `searchDestinations()` and submit the selected `DestinationOption.city_code`, never a free-text city name.
- Missing or invalid city data returns `请选择目的地城市后再发布同行计划。`.

---

### Task 1: Accept and Validate an Internal Fallback City

**Files:**
- Modify: `backend/app/modules/community/schemas.py`
- Modify: `backend/app/modules/community/service.py`
- Modify: `backend/tests/community/test_companion_plans.py`
- Modify: `backend/tests/community/test_companion_plan_router.py`

**Interfaces:**
- `CompanionPlanCreate.city_code: str | None` is an optional six-digit fallback.
- `CommunityService.create_companion_plan_from_itinerary()` resolves `snapshot_city_code or body.city_code`.

- [ ] **Step 1: Write failing service and router tests**

```python
@pytest.mark.anyio
async def test_plan_uses_selected_fallback_city_only_when_itinerary_has_no_city(session):
    plan = await service.create_companion_plan_from_itinerary(
        owner.id,
        itinerary_without_city.id,
        CompanionPlanCreate(city_code="330100", **metadata),
    )
    assert plan.city_code == "330100"
    assert itinerary_without_city.id == plan.itinerary_id

@pytest.mark.anyio
async def test_trusted_itinerary_city_overrides_submitted_fallback(session):
    plan = await service.create_companion_plan_from_itinerary(
        owner.id,
        itinerary_with_city.id,
        CompanionPlanCreate(city_code="310000", **metadata),
    )
    assert plan.city_code == "330100"
```

Add HTTP assertions that an itinerary without city returns `422` and the exact Chinese message when `city_code` is absent, and returns `201` with a valid selected code.

- [ ] **Step 2: Run tests to verify they fail**

Run from `backend`: `pytest tests/community/test_companion_plans.py tests/community/test_companion_plan_router.py -k "fallback_city or destination_city" -v`

Expected: FAIL because `CompanionPlanCreate` does not accept the fallback and the service rejects the itinerary first.

- [ ] **Step 3: Implement schema and service resolution**

```python
class CompanionPlanCreate(BaseModel):
    city_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    party_size: int = Field(ge=2, le=12)
    # existing budget, pace, tags, and intro fields remain unchanged

# CommunityService.create_companion_plan_from_itinerary
snapshot_city_code = _companion_city_code(snapshot)
city_code = snapshot_city_code or body.city_code
if city_code is None:
    raise CommunityError(
        "COMPANION_DESTINATION_REQUIRED",
        "请选择目的地城市后再发布同行计划。",
    )
```

Pass the resolved value to `_create_companion_plan`. Do not change `Itinerary`, `ItineraryVersion`, events, or snapshots. Keep the activity creation contract unchanged because it already requires a controlled city code.

- [ ] **Step 4: Run focused backend verification**

Run: `pytest tests/community/test_companion_plans.py tests/community/test_companion_plan_router.py -v`

Expected: PASS.

- [ ] **Step 5: Commit backend fallback behavior**

```bash
git add backend/app/modules/community/schemas.py backend/app/modules/community/service.py backend/tests/community/test_companion_plans.py backend/tests/community/test_companion_plan_router.py
```

### Task 2: Add the Conditional City Selector to Publishing

**Files:**
- Modify: `frontend-c/src/features/community/CompanionPlanPublishPage.vue`
- Modify: `frontend-c/src/features/community/companionPlansApi.ts`
- Modify: `frontend-c/src/features/community/companionPlans.test.ts`

**Interfaces:**
- Consumes `DestinationOption` and `searchDestinations(query)` from `@/features/itineraries/destinationsApi`.
- Sends `city_code` only in `publishCompanionPlan()` when the selected fallback destination exists.
- Uses the itinerary destination city where it can be inferred, and otherwise requires one selected option before enabling submit.

- [ ] **Step 1: Write view-model tests**

```ts
it('requires a selected city only when the itinerary has no inferred city', () => {
  expect(requiresDestinationSelection({ days: [{ events: [{ poi_snapshot: { city: '330100' } }] }] })).toBe(false)
  expect(requiresDestinationSelection({ days: [{ events: [{ poi_snapshot: {} }] }] })).toBe(true)
})

it('includes the selected internal code but not a free-text city name in publish payload', () => {
  expect(publishPayload(form, { name: '杭州', city_code: '330100' })).toMatchObject({ city_code: '330100' })
  expect(publishPayload(form, null)).not.toHaveProperty('city_name')
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `frontend-c`: `npm run test -- companionPlans.test.ts`

Expected: FAIL because city fallback helpers and the selector payload do not exist.

- [ ] **Step 3: Implement automatic inference and accessible search selection**

Add helpers that inspect `itinerary.snapshot.destination?.city_code` first, then `day.events[].poi_snapshot.city` for a six-digit code. If inference succeeds, render a read-only destination row with a human label from `destination.name` when available, otherwise “行程已识别目的地”. Do not render a raw code.

If inference fails, render an explicit label `目的地城市`, a text search input, debounced `searchDestinations()` result list, keyboard selection with ArrowUp/ArrowDown/Enter/Escape, and a selected city display using `DestinationOption.name` and `display_address`. Clear the selected option if its visible query changes. Announce loading and errors accessibly.

Disable submit while `requiresDestinationSelection` is true and no selected option exists; show `请选择同行计划的目的地城市。`. Pass `city_code: selectedDestination?.city_code` into `publishCompanionPlan()`. Do not persist this selection into the itinerary or show it outside the publish page.

- [ ] **Step 4: Run frontend verification**

Run: `npm run test -- companionPlans.test.ts; npm run typecheck; npm run build`

Expected: all commands PASS.

- [ ] **Step 5: Commit the publish-page correction**

```bash
git add frontend-c/src/features/community/CompanionPlanPublishPage.vue frontend-c/src/features/community/companionPlansApi.ts frontend-c/src/features/community/companionPlans.test.ts
```

## Plan Self-Review

### Spec coverage

- Automatic trusted city detection: Task 1 service resolution and Task 2 publish helper.
- Controlled fallback city selection without raw city-code UI: Task 2.
- Trust order, missing-city error, and no itinerary mutation: Task 1 tests and implementation.

### Type consistency

- Backend and frontend use the same optional field name: `city_code`.
- The frontend only obtains it from `DestinationOption.city_code` and sends it through `publishCompanionPlan()`.

### Scope check

This plan modifies only companion-plan publishing from existing itineraries. It does not alter short-activity publishing, itinerary schema, route facts, field notes, or public discovery behavior.
