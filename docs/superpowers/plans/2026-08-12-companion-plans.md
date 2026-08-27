# Companion Plans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current companion-request board with reviewed, itinerary-backed companion plans that support travel and short activities, applications, automatic group chat and itinerary collaboration, capacity control, member lifecycle, and a premium responsive discovery experience.

**Architecture:** Extend `CompanionRequest` and `CompanionApplication`; do not create a parallel team aggregate. A companion plan always owns an itinerary reference, and all acceptance, removal, exit, capacity, and completion changes execute transactionally across community, itinerary, and chat facts. The consumer experience provides discovery, detail, request publishing, and workspace status views on top of those durable APIs.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy async, Alembic/MySQL, pytest, Vue 3 Composition API, TypeScript, Vite, Element Plus, lucide-vue-next.

## Global Constraints

- Extend `CompanionRequest`, `CompanionApplication`, `TripCollaborator`, `Conversation`, and `ConversationMember`; do not create a parallel travel-group model.
- A companion plan always references one itinerary. `trip_kind="trip"` uses an existing itinerary; `trip_kind="activity"` creates one light one-day itinerary server-side.
- Business status is `open`, `full`, `closed`, `cancelled`, or `completed`; moderation remains the separate existing `review_status` state.
- Only `review_status="approved"` and `status="open"` plans can appear in public discovery and accept applications.
- `party_size` includes the owner. `accepted_count` starts at `1`, must not exceed `party_size`, and a full plan stops new applications immediately.
- Accepting an application must atomically grant the applicant itinerary `editor` access, create/reuse the companion group conversation, add active chat membership, persist the conversation ID, increase capacity, and emit Outbox events.
- Removing or exiting retains historic itinerary changes but revokes future itinerary editing and group-chat access. Completion retains readable chat history, blocks new messages, and leaves only the owner able to edit the itinerary.
- Application text is required. Before acceptance, do not expose contacts, exact meeting points, private itinerary notes, group membership, or protected route data.
- Apply existing bidirectional `UserBlock` checks before application, acceptance, group membership, and any new member relation. Do not disclose which user imposed the block.
- Community does not write notification rows. Lifecycle events are durable Outbox facts consumed by notifications.
- Do not implement identity verification, credit scores, deposits, payment splitting, insurance, automatic completion, waitlists, or multi-owner management.
- Preserve the Field / Travel palette and use motion only for factual state changes. Honor `prefers-reduced-motion`.
- Verify migrations on Compose MySQL with `alembic upgrade head`, `alembic downgrade -1`, and `alembic upgrade head`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/alembic/versions/20260812_0038_companion_plans.py` | Add companion plan fields, allowed status constraint, application conversation link, indexes, constraints, and MySQL rollback. |
| `backend/app/modules/community/models.py` | Persist itinerary-backed plan metadata and accepted application chat reference. |
| `backend/app/modules/community/schemas.py` | Publish, activity, list/detail, application, member, lifecycle, and response schemas. |
| `backend/app/modules/community/service.py` | Plan creation, snapshot projection, discovery, private detail, applications, acceptance, member lifecycle, block checks, and Outbox events. |
| `backend/app/modules/community/router.py` | Public and authenticated companion plan HTTP routes. |
| `backend/app/modules/itineraries/router.py` | Register owner/editor route for publishing a plan from an existing itinerary. |
| `backend/app/modules/itineraries/service.py` | Create a one-day light itinerary for an activity in the surrounding community transaction. |
| `backend/app/modules/chat/service.py` | Deny messages in completed companion-group conversations while preserving readable history. |
| `backend/app/modules/admin/router.py` | Return safe plan metadata for review and retain review-state transitions. |
| `backend/tests/community/test_companion_plans.py` | Domain, transaction, capacity, block, removal, and completion tests. |
| `backend/tests/community/test_companion_plan_router.py` | HTTP authorization, visibility, creation, application, acceptance, and lifecycle tests. |
| `backend/tests/chat/test_services.py` | Completed companion chat is readable but write-blocked. |
| `frontend-c/src/features/community/companionPlansApi.ts` | Typed list/detail/publish/application/member lifecycle client. |
| `frontend-c/src/features/community/CompanionPlansPage.vue` | Discovery page, filters, featured plan, list states, and motion. |
| `frontend-c/src/features/community/CompanionPlanDetailPage.vue` | Public/private detail, application, owner management, member controls, and safe data visibility. |
| `frontend-c/src/features/community/CompanionPlanPublishPage.vue` | Existing-itinerary publish form. |
| `frontend-c/src/features/community/CompanionActivityPublishPage.vue` | One-day activity and companion plan creation form. |
| `frontend-c/src/features/community/components/CompanionPlanCard.vue` | Route and capacity summary card. |
| `frontend-c/src/features/community/components/CompanionPlanTimeline.vue` | Public/protected itinerary snapshot timeline. |
| `frontend-c/src/features/community/companionPlans.test.ts` | API, state formatting, eligibility, and route tests. |
| `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue` | Companion-plan entry and shared-plan status/actions. |
| `frontend-c/src/router/index.ts` | Detail and publishing routes. |
| `frontend-b/src/features/admin/pages/OperationsPage.vue` | Safe plan type/date/capacity display in moderation queue. |
| `docs/API设计.md` | Exact companion-plan contract and privacy boundaries. |
| `docs/本地验收使用手册.md` | Publication, moderation, application, collaboration, member, and completion acceptance procedure. |

## Task 1: Persist Companion Plan Facts

**Files:**
- Modify: `backend/app/modules/community/models.py`
- Create: `backend/alembic/versions/20260812_0038_companion_plans.py`
- Test: `backend/tests/community/test_companion_plan_models.py`

**Interfaces:**
- Produces an itinerary-backed `CompanionRequest` with plan metadata and a nullable `conversation_id`.
- Produces nullable `CompanionApplication.conversation_id`.
- Keeps historical requests valid by adding nullable fields and backfilling no records.

- [ ] **Step 1: Write failing ORM constraint tests**

```python
@pytest.mark.anyio
async def test_companion_plan_requires_valid_capacity_and_business_status(session):
    request = CompanionRequest(
        owner_id=user.id,
        title="Hangzhou walk",
        description="Slow route",
        itinerary_id=itinerary.id,
        trip_kind="trip",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 2),
        party_size=2,
        accepted_count=3,
        travel_pace="slow",
        interest_tags=["citywalk"],
        intro_text="Walk and take photos.",
        status="open",
    )
    session.add(request)
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: Run the focused model test and verify it fails**

Run: `pytest tests/community/test_companion_plan_models.py -v`

Expected: FAIL because companion-plan fields and constraints do not exist.

- [ ] **Step 3: Add model fields and a MySQL-safe migration**

Add these ORM fields:

```python
itinerary_id: Mapped[str | None] = mapped_column(ForeignKey("itineraries.id", ondelete="SET NULL"), index=True)
trip_kind: Mapped[str | None] = mapped_column(String(16))
start_date: Mapped[date | None] = mapped_column(Date)
end_date: Mapped[date | None] = mapped_column(Date)
party_size: Mapped[int | None] = mapped_column(Integer)
accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
budget_min: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2))
budget_max: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2))
currency: Mapped[str | None] = mapped_column(String(3))
travel_pace: Mapped[str | None] = mapped_column(String(16))
interest_tags: Mapped[list[str] | None] = mapped_column(JSON)
intro_text: Mapped[str | None] = mapped_column(Text)
conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), index=True)

# CompanionApplication
conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
```

Replace the existing request status check with `status IN ('open', 'full', 'closed', 'cancelled', 'completed')`. Add checks for date order, `party_size >= 2`, `accepted_count >= 1 AND accepted_count <= party_size`, `budget_min <= budget_max` when both values exist, valid trip kind and pace values. Add indexes for public discovery: `(review_status, status, start_date)`, `city_code`, `trip_kind`, and `itinerary_id`. The migration must use named foreign keys/indexes/checks and reverse foreign keys before their supporting indexes during downgrade.

- [ ] **Step 4: Run model tests and migration lifecycle**

Run: `pytest tests/community/test_companion_plan_models.py -v`

Expected: PASS.

Run from `backend`: `alembic upgrade head; alembic downgrade -1; alembic upgrade head`

Expected: all commands complete against Compose MySQL and return the database to the new head.

- [ ] **Step 5: Commit persistence**

```bash
git add backend/app/modules/community/models.py backend/alembic/versions/20260812_0038_companion_plans.py backend/tests/community/test_companion_plan_models.py
```

## Task 2: Create Reviewed Trips and Activities

**Files:**
- Modify: `backend/app/modules/community/schemas.py`
- Modify: `backend/app/modules/community/service.py`
- Modify: `backend/app/modules/community/router.py`
- Modify: `backend/app/modules/itineraries/router.py`
- Modify: `backend/app/modules/itineraries/service.py`
- Test: `backend/tests/community/test_companion_plans.py`
- Test: `backend/tests/community/test_companion_plan_router.py`

**Interfaces:**
- `CompanionPlanCreate` accepts public plan metadata but never accepts a route snapshot.
- `CommunityService.create_companion_plan_from_itinerary(actor_id, itinerary_id, body)` returns a pending-review plan.
- `CommunityService.create_companion_activity(actor_id, body)` creates a one-day itinerary and pending-review activity in one transaction.

- [ ] **Step 1: Write failing creation tests**

```python
@pytest.mark.anyio
async def test_editor_can_publish_plan_from_nonempty_itinerary(session):
    plan = await service.create_companion_plan_from_itinerary(editor.id, itinerary.id, CompanionPlanCreate(
        party_size=3,
        budget_min=600,
        budget_max=900,
        currency="CNY",
        travel_pace="balanced",
        interest_tags=["citywalk", "food"],
        intro_text="Want to walk, eat, and keep the pace relaxed.",
    ))
    assert plan.status == "open"
    assert plan.review_status == "pending_review"
    assert plan.accepted_count == 1
    assert plan.trip_kind == "trip"
    assert plan.start_date == itinerary.start_date

@pytest.mark.anyio
async def test_activity_creation_rolls_back_itinerary_when_plan_validation_fails(session):
    with pytest.raises(CommunityError, match="INVALID_COMPANION_CAPACITY"):
        await service.create_companion_activity(owner.id, invalid_body)
    assert await session.scalar(select(func.count(Itinerary.id))) == 0
```

- [ ] **Step 2: Run creation tests and verify failure**

Run: `pytest tests/community/test_companion_plans.py -k "create" -v`

Expected: FAIL because the schemas and creation methods do not exist.

- [ ] **Step 3: Define exact publish and activity schemas**

```python
class CompanionPlanCreate(BaseModel):
    party_size: int = Field(ge=2, le=12)
    budget_min: Decimal | None = Field(default=None, ge=0)
    budget_max: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    travel_pace: Literal["slow", "balanced", "packed"]
    interest_tags: list[str] = Field(min_length=1, max_length=8)
    intro_text: str = Field(min_length=1, max_length=2_000)

class CompanionActivityCreate(CompanionPlanCreate):
    title: str = Field(min_length=1, max_length=200)
    city_code: str = Field(min_length=1, max_length=32)
    activity_date: date
    starts_at: datetime
    ends_at: datetime
    poi_id: str = Field(min_length=1, max_length=128)
```

Require `budget_min` and `budget_max` together with `currency`, validate tag membership against a single server-side `COMPANION_INTEREST_TAGS` set, and validate `starts_at < ends_at` on the same activity date.

- [ ] **Step 4: Implement service and routes**

`create_companion_plan_from_itinerary` must validate owner or accepted editor using the existing itinerary permission rules, load the selected current itinerary snapshot, require at least one event, derive city code from the first event's `poi_snapshot.city` or the manual-plan destination snapshot, and project only title/date/route count into public companion fields. It must set `status="open"`, `review_status="pending_review"`, `accepted_count=1`, and `trip_kind="trip"`.

For activities, verify the POI through the established map service, create a one-day itinerary containing the verified event and time range, record its initial version, then create `trip_kind="activity"` plan within the same session transaction. Do not use `create_manual_plan`, because it commits before companion creation.

Register:

```python
@router.post("/{itinerary_id}/companion-requests", response_model=CompanionPlanResponse, status_code=201)
@companion_router.post(":activity", response_model=CompanionPlanResponse, status_code=201)
```

Map permission errors to `403`, missing itinerary to `404`, invalid publish/activity content to `422`, and do not leave partial records after failure.

- [ ] **Step 5: Run creation and router tests**

Run: `pytest tests/community/test_companion_plans.py tests/community/test_companion_plan_router.py -k "create or activity" -v`

Expected: PASS.

- [ ] **Step 6: Commit publication flow**

```bash
git add backend/app/modules/community/schemas.py backend/app/modules/community/service.py backend/app/modules/community/router.py backend/app/modules/itineraries/router.py backend/app/modules/itineraries/service.py backend/tests/community/test_companion_plans.py backend/tests/community/test_companion_plan_router.py
```

## Task 3: Discover and Read Plans With Safe Visibility

**Files:**
- Modify: `backend/app/modules/community/schemas.py`
- Modify: `backend/app/modules/community/service.py`
- Modify: `backend/app/modules/community/router.py`
- Modify: `backend/app/modules/admin/router.py`
- Test: `backend/tests/community/test_companion_plans.py`
- Test: `backend/tests/community/test_companion_plan_router.py`
- Test: `backend/tests/admin/test_companion_plan_admin.py`

**Interfaces:**
- `GET /companion-requests` is cursor-paginated and returns approved/open plans only.
- `GET /companion-requests/{request_id}` returns public detail to visitors and protected member detail only to owner/accepted members.
- `GET /companion-requests/mine` returns owned, accepted, and pending-application plans for the current user.

- [ ] **Step 1: Write failing visibility and pagination tests**

```python
@pytest.mark.anyio
async def test_public_discovery_filters_to_approved_open_plans(session):
    page = await service.list_public_companion_plans(
        city_code="330100", start_date=date(2026, 10, 1), end_date=date(2026, 10, 31),
        trip_kind="trip", travel_pace="slow", tags=["citywalk"], has_slots=True, limit=20, cursor=None,
    )
    assert [item.id for item in page.items] == [approved_open_plan.id]

@pytest.mark.anyio
async def test_public_detail_hides_members_group_and_private_notes(session):
    detail = await service.get_companion_plan_detail(plan.id, viewer_id=None)
    assert detail.conversation_id is None
    assert detail.members == []
    assert detail.protected_itinerary is None
```

- [ ] **Step 2: Run discovery tests and verify failure**

Run: `pytest tests/community/test_companion_plans.py -k "discovery or detail" -v`

Expected: FAIL because typed plan responses and filtered list/detail methods do not exist.

- [ ] **Step 3: Implement response projection and stable discovery**

Create `CompanionPlanSummaryResponse`, `CompanionPlanDetailResponse`, `CompanionPlanMemberResponse`, and `CompanionPlanPage`. Public fields are title, city/date/type, capacity, budget, pace, tags, intro, route count, cover candidate, review-safe status, and current user's application state if authenticated. Do not return owner phone, private notes, exact meeting information, chat ID, member IDs, or internal itinerary snapshot to visitors.

Use a stable ordering of `start_date ASC, created_at DESC, id DESC`, with cursor containing only a signed/validated combination of those values or an opaque record ID resolved server-side. Apply city code, overlapping date range, trip kind, pace, tag containment, and `accepted_count < party_size` filters before pagination.

For accepted members and owners, return member display data, `conversation_id`, linked itinerary ID, and the protected snapshot needed for the group detail. A pending applicant still receives public detail only.

- [ ] **Step 4: Add safe admin projection**

Keep existing review endpoint/status logic, but make the admin list return plan type, itinerary presence, dates, party size, accepted count, pace, tags, and intro text. It must never return private itinerary snapshots, conversations, messages, block relationships, or contacts.

- [ ] **Step 5: Run discovery/admin suites**

Run: `pytest tests/community/test_companion_plans.py tests/community/test_companion_plan_router.py tests/admin/test_companion_plan_admin.py -v`

Expected: PASS.

- [ ] **Step 6: Commit discovery and visibility**

```bash
git add backend/app/modules/community backend/app/modules/admin/router.py backend/tests/community/test_companion_plans.py backend/tests/community/test_companion_plan_router.py backend/tests/admin/test_companion_plan_admin.py
```

## Task 4: Apply, Accept, and Manage Membership Atomically

**Files:**
- Modify: `backend/app/modules/community/schemas.py`
- Modify: `backend/app/modules/community/service.py`
- Modify: `backend/app/modules/community/router.py`
- Test: `backend/tests/community/test_companion_plans.py`
- Test: `backend/tests/community/test_companion_plan_router.py`

**Interfaces:**
- Application request requires `message` with 1-1,000 non-whitespace characters.
- `accept_companion_application` returns application, group conversation, resulting plan status, and idempotent-safe member facts.
- Produces owner member removal, member leave, close/reopen, and completion methods.

- [ ] **Step 1: Write failing atomic acceptance and capacity tests**

```python
@pytest.mark.anyio
async def test_acceptance_creates_editor_group_member_and_full_state_in_one_transaction(session):
    application, conversation = await service.accept_companion_application(application.id, owner.id)
    collaborator = await session.scalar(select(TripCollaborator).where(
        TripCollaborator.itinerary_id == plan.itinerary_id,
        TripCollaborator.user_id == applicant.id,
    ))
    assert application.status == "accepted"
    assert application.conversation_id == conversation.id == plan.conversation_id
    assert collaborator.role == "editor" and collaborator.status == "accepted"
    assert plan.accepted_count == plan.party_size
    assert plan.status == "full"

@pytest.mark.anyio
async def test_acceptance_rejects_blocked_or_full_plan_without_side_effects(session):
    with pytest.raises(CommunityError, match="COMPANION_PLAN_FULL"):
        await service.accept_companion_application(pending_application.id, owner.id)
    assert pending_application.status == "pending"
    assert await session.scalar(select(Conversation).where(Conversation.title == plan.title)) is None
```

- [ ] **Step 2: Run membership tests and verify failure**

Run: `pytest tests/community/test_companion_plans.py -k "accept or member or leave" -v`

Expected: FAIL because capacity, chat references, block checks, and member lifecycle are absent.

- [ ] **Step 3: Implement required applications and block checks**

Change `CompanionApplicationCreate.message` to `Field(min_length=1, max_length=1000)`. In application creation, lock/read the plan and require approved/open/not-full; reject self-application, existing application, and a block between applicant and owner. At acceptance, check blocks between the applicant and every current accepted member before group membership is written.

Use `select(CompanionRequest).where(...).with_for_update()` for acceptance and capacity changes. Preserve the unique request/applicant constraint; an existing pending application returns the same row only when the request is still eligible, otherwise returns its current state without mutation.

- [ ] **Step 4: Implement transactionally consistent acceptance**

Inside one transaction:

```python
plan = await _locked_plan_for_owner(application.request_id, owner_id)
_require_acceptance_allowed(plan, application)
await _require_no_member_blocks(applicant_id, plan.id)
conversation = await _get_or_create_companion_group(plan)
await _activate_conversation_member(conversation.id, applicant_id)
await _grant_editor(plan.itinerary_id, applicant_id)
application.status = "accepted"
application.conversation_id = conversation.id
plan.accepted_count += 1
if plan.accepted_count == plan.party_size:
    plan.status = "full"
_event("companion_application.accepted", ...)
```

`_get_or_create_companion_group` creates exactly one `Conversation(conversation_type="companion_group", title=plan.title)` and active owner membership if `plan.conversation_id` is null. `_activate_conversation_member` revives a prior member only if the plan permits a new accepted membership; otherwise it creates one. `_grant_editor` creates or revives `TripCollaborator` without downgrading the owner.

- [ ] **Step 5: Implement close, remove, leave, and completion**

Add routes and service methods:

```python
DELETE /companion-requests/{request_id}/members/{user_id}
POST /companion-requests/{request_id}:leave
POST /companion-requests/{request_id}:complete
```

Removal and leave set the relevant collaborator to `revoked` and conversation member `left_at=utc_now()`, preserve itinerary rows/version history, decrement capacity, and move `full` back to `open`. Owner removal of self is forbidden. `complete` requires owner, sets `status="completed"`, revokes all non-owner collaborators, retains chat membership for history, and emits a completion Outbox event. Closing/reopening requests changes only recruitment state; it cannot reopen cancelled/completed plans or bypass review.

- [ ] **Step 6: Add router tests and run membership suites**

Test required-message `422`, unauthenticated `401`, applicant/owner permissions, blocked `403`, full `409`, accepted response with conversation ID, removed/left member no longer reads itinerary, completed plan rejects new applications, and capacity reopens after a member exits.

Run: `pytest tests/community/test_companion_plans.py tests/community/test_companion_plan_router.py -v`

Expected: PASS.

- [ ] **Step 7: Commit membership lifecycle**

```bash
git add backend/app/modules/community/schemas.py backend/app/modules/community/service.py backend/app/modules/community/router.py backend/tests/community/test_companion_plans.py backend/tests/community/test_companion_plan_router.py
```

## Task 5: Enforce Completed-Group Chat Rules and Notifications

**Files:**
- Modify: `backend/app/modules/chat/service.py`
- Modify: `backend/app/workers/domain_handlers.py`
- Test: `backend/tests/chat/test_services.py`
- Test: `backend/tests/workers/test_companion_notifications.py`

**Interfaces:**
- Active members can read history after plan completion but `ChatService.create_message` rejects new companion-group messages with `COMPANION_PLAN_COMPLETED`.
- Worker maps companion lifecycle Outbox events to notifications without community writing notification rows.

- [ ] **Step 1: Write failing chat and notification tests**

```python
@pytest.mark.anyio
async def test_completed_companion_group_keeps_history_readable_and_blocks_sends(session):
    messages, _ = await ChatService(session).list_messages(plan.conversation_id, member.id)
    assert [message.id for message in messages] == [historic_message.id]
    with pytest.raises(ChatError, match="COMPANION_PLAN_COMPLETED"):
        await ChatService(session).create_message(plan.conversation_id, member.id, "retry-key", "text", "Still there?")

def test_companion_acceptance_notification_targets_applicant_only():
    event = {"event_type": "companion_application.accepted", "payload": {"applicant_id": "user-2", "request_id": "plan-1"}}
    assert notification_targets(event) == ["user-2"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/chat/test_services.py -k companion; pytest tests/workers/test_companion_notifications.py -v`

Expected: FAIL because completed group writes are currently allowed and event mappings are absent.

- [ ] **Step 3: Gate companion-group sends by plan state**

In `ChatService.create_message`, after validating active membership and loading the conversation, query `CompanionRequest` by `conversation_id` when `conversation_type == "companion_group"`. If a matching plan has `status == "completed"`, raise `ChatError("COMPANION_PLAN_COMPLETED", "This companion plan has ended; group history remains available.")`. Do not change `list_messages`, so valid members retain history. Removed/left users remain blocked by existing membership checks.

- [ ] **Step 4: Map lifecycle events in the worker**

Register accepted, rejected, withdrawn, removed, left, full, and completed events in `register_domain_handlers()` with `_notify_user`. Each event payload must contain only the applicable `owner_id`, `applicant_id`, `user_id`, or `recipient_ids`, plus plan/application IDs and a reason-safe status. The existing Outbox consumer idempotency remains the delivery boundary. Never include message content, private itinerary snapshots, phone numbers, or block metadata.

- [ ] **Step 5: Run chat/worker verification**

Run: `pytest tests/chat/test_services.py tests/workers/test_companion_notifications.py -v`

Expected: PASS.

- [ ] **Step 6: Commit chat and notification behavior**

```bash
git add backend/app/modules/chat/service.py backend/app/workers/domain_handlers.py backend/tests/chat/test_services.py backend/tests/workers/test_companion_notifications.py
```

## Task 6: Build Typed Consumer APIs, Discovery, and Detail

**Files:**
- Create: `frontend-c/src/features/community/companionPlansApi.ts`
- Create: `frontend-c/src/features/community/components/CompanionPlanCard.vue`
- Create: `frontend-c/src/features/community/components/CompanionPlanTimeline.vue`
- Create: `frontend-c/src/features/community/CompanionPlansPage.vue`
- Create: `frontend-c/src/features/community/CompanionPlanDetailPage.vue`
- Create: `frontend-c/src/features/community/companionPlans.test.ts`
- Modify: `frontend-c/src/router/index.ts`
- Modify: `frontend-c/src/App.vue`

**Interfaces:**
- Produces `CompanionPlanSummary`, `CompanionPlanDetail`, `CompanionApplication`, and typed lifecycle methods.
- Replaces the public `/companions` request list with discovery, and adds `/companions/:requestId` detail.

- [ ] **Step 1: Write API and pure-state tests**

```ts
it('formats remaining seats from accepted count and party size', () => {
  expect(remainingSeats({ accepted_count: 2, party_size: 4 } as CompanionPlanSummary)).toBe(2)
})

it('submits a required application message', async () => {
  await applyToCompanionPlan('plan-1', 'I enjoy early walks and food markets.')
  expect(api.post).toHaveBeenCalledWith('/companion-requests/plan-1/applications', {
    message: 'I enjoy early walks and food markets.',
  })
})
```

- [ ] **Step 2: Run frontend tests and verify failure**

Run from `frontend-c`: `npm run test -- companionPlans.test.ts`

Expected: FAIL because the client and helpers do not exist.

- [ ] **Step 3: Implement client contracts and routes**

Model the exact backend schemas in `companionPlansApi.ts`; use `ItinerarySnapshot` only for member-protected route data. Add public lazy routes:

```ts
{ path: '/companions', component: () => import('@/features/community/CompanionPlansPage.vue') },
{ path: '/companions/:requestId', component: () => import('@/features/community/CompanionPlanDetailPage.vue'), props: true },
```

Change the navigation label to `同行计划`. Preserve `/companions` as public; application and management methods rely on the existing consumer auth interceptor and redirect unauthenticated users to login with `redirect=/companions/{id}`.

- [ ] **Step 4: Implement the discovery page**

Build a Field / Travel “departure window” discovery page with destination, overlapping date range, trip/activity, pace, tag, and remaining-seat filters. Display a featured record followed by route-oriented cards. Every card must show destination, dates, type, capacity, remaining seats, budget, pace, tags, route stop count, owner intro excerpt, and one of: apply, pending, full, closed, or completed state.

Use 40-70ms staggered entries only for first load/filter replacement. Use `opacity` and `transform`; render immediate stable content under `prefers-reduced-motion`. Provide skeleton loading, error retry, resettable empty state, keyboard focus, and responsive grid behavior without decorative gradients.

- [ ] **Step 5: Implement the detail page**

The detail page must load public data first and augment it based on authenticated role. Render public route overview, plan metadata, owner intro, safety notice, and a required application message form. Do not render protected data from the public payload.

For pending applicants: show submitted state and withdraw control. For owner: show applications, accept/reject, member removal, capacity editing, close/reopen, and completion actions. For accepted members: show group-chat and shared-workspace actions, member list, protected route context, and leave action. On acceptance, route to `/messages/{conversation_id}`; on workspace action, route to `/itineraries/{itinerary_id}`.

Desktop uses a sticky unframed action rail; mobile uses a stable bottom action bar. Tie member/capacity state transitions to 160-320ms `opacity`/`transform` feedback only; do not animate success before the API response.

- [ ] **Step 6: Run consumer checks**

Run: `npm run test -- companionPlans.test.ts; npm run typecheck; npm run build`

Expected: all commands PASS.

- [ ] **Step 7: Commit discovery and detail UI**

```bash
git add frontend-c/src/features/community/companionPlansApi.ts frontend-c/src/features/community/components/CompanionPlanCard.vue frontend-c/src/features/community/components/CompanionPlanTimeline.vue frontend-c/src/features/community/CompanionPlansPage.vue frontend-c/src/features/community/CompanionPlanDetailPage.vue frontend-c/src/features/community/companionPlans.test.ts frontend-c/src/router/index.ts frontend-c/src/App.vue
```

## Task 7: Add Plan Publishing and Workspace Collaboration Surfaces

**Files:**
- Create: `frontend-c/src/features/community/CompanionPlanPublishPage.vue`
- Create: `frontend-c/src/features/community/CompanionActivityPublishPage.vue`
- Modify: `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue`
- Modify: `frontend-c/src/features/itineraries/api.ts`
- Modify: `frontend-c/src/router/index.ts`
- Modify: `frontend-c/src/features/community/companionPlans.test.ts`

**Interfaces:**
- `publishCompanionPlan(itineraryId, body)` creates a plan from an editable existing itinerary.
- `publishCompanionActivity(body)` creates an activity itinerary and plan atomically.
- Workspace receives current companion-plan summary for editor/owner context.

- [ ] **Step 1: Write publishing eligibility tests**

```ts
it('requires capacity, pace, tags, and intro before publishing a companion plan', () => {
  expect(canPublishPlan({ partySize: 1, pace: 'slow', tags: ['citywalk'], intro: 'Hello' })).toBe(false)
  expect(canPublishPlan({ partySize: 3, pace: 'balanced', tags: ['citywalk'], intro: 'Travel slowly.' })).toBe(true)
})

it('routes accepted members into the group conversation', () => {
  expect(acceptedDestination({ conversation_id: 'conversation-1' })).toBe('/messages/conversation-1')
})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `npm run test -- companionPlans.test.ts`

Expected: FAIL because publishing pages and helpers do not exist.

- [ ] **Step 3: Build existing-itinerary publishing page**

Add `/itineraries/:itineraryId/publish-companion-plan` behind consumer auth. Load the editable itinerary and current version, show a read-only route preview, and collect capacity, paired budget/currency, pace, controlled tags, and intro. Explain that route order stays collaboratively editable after acceptance while contacts and exact meeting details remain private. Submit only metadata; the server derives route and dates.

- [ ] **Step 4: Build short-activity publishing page**

Add `/companions/publish-activity` behind consumer auth. Collect title, city, date, start/end time, verified POI, capacity, optional paired budget/currency, pace, tags, and intro. Search POIs through the existing map API; do not allow unverified manual location data. Submit once to the activity API and route to a private pending-plan state or the user's plan list.

- [ ] **Step 5: Extend the workspace surface**

For itinerary owner/editor, show plan status, capacity, participant count, and group-chat link only when the user is an accepted plan member. Owner sees a “发起同行计划” command when no active plan exists and close/complete actions when one exists. Member sees a concise “同行协作中” state and never sees owner-only controls. Reuse the existing visible version-conflict UI rather than adding a second collaboration conflict mechanism.

- [ ] **Step 6: Run consumer verification**

Run: `npm run test -- companionPlans.test.ts; npm run typecheck; npm run build`

Expected: PASS.

- [ ] **Step 7: Commit publishing and workspace integration**

```bash
git add frontend-c/src/features/community/CompanionPlanPublishPage.vue frontend-c/src/features/community/CompanionActivityPublishPage.vue frontend-c/src/features/community/companionPlansApi.ts frontend-c/src/features/community/companionPlans.test.ts frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue frontend-c/src/features/itineraries/api.ts frontend-c/src/router/index.ts
```

## Task 8: Update Operations, Documentation, and Acceptance

**Files:**
- Modify: `frontend-b/src/features/admin/pages/OperationsPage.vue`
- Modify: `frontend-b/src/features/admin/services/operations.ts`
- Modify: `docs/API设计.md`
- Modify: `docs/本地验收使用手册.md`
- Modify: `docs/项目进度与完成度总结.md`
- Test: `backend/tests/admin/test_companion_plan_admin.py`

**Interfaces:**
- The admin moderation queue identifies plan type, dates, capacity, accepted count, and review state without exposing private data.
- Documentation matches exact status, privacy, application, group, collaboration, completion, and notification semantics.

- [ ] **Step 1: Write failing admin-safe-response regression test**

```python
def test_admin_companion_queue_exposes_plan_metadata_not_private_route_or_chat(client, admin_headers):
    response = client.get('/api/v1/admin/companion-requests?status=pending_review', headers=admin_headers)
    item = response.json()['items'][0]
    assert item['trip_kind'] == 'trip'
    assert item['party_size'] == 3
    assert 'itinerary_snapshot' not in item
    assert 'conversation_id' not in item
    assert 'phone' not in item
```

- [ ] **Step 2: Run the test and verify failure**

Run: `pytest tests/admin/test_companion_plan_admin.py -v`

Expected: FAIL because the moderation projection does not yet contain safe companion-plan metadata.

- [ ] **Step 3: Update admin presentation and documentation**

Update the admin request type label to `同行计划` and display plan kind, dates, capacity, accepted count, pace, tags, intro, business status, review status, and reason. Preserve existing approve/reject audit behavior. Do not add management actions that bypass owner lifecycle rules.

Document all actual routes, required application explanation, public/protected fields, accepted-editor behavior, member removal/exit/completion semantics, completed group read/write behavior, block enforcement, Outbox notification ownership, and data excluded from public/RAG domains.

- [ ] **Step 4: Run final backend/frontend verification**

Run from `backend`:

```bash
pytest tests/community/test_companion_plan_models.py tests/community/test_companion_plans.py tests/community/test_companion_plan_router.py tests/chat/test_services.py tests/workers/test_companion_notifications.py tests/admin/test_companion_plan_admin.py -v
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Run from `frontend-c` and `frontend-b`:

```bash
npm run typecheck
npm run build
```

Perform browser acceptance at desktop and mobile viewports:

```text
1. Publish and approve a multi-day plan from a populated itinerary.
2. Publish and approve a one-day verified-POI activity.
3. Browse/filter publicly; submit a nonempty application as another user.
4. Accept it; verify group-chat navigation and itinerary editor permission.
5. Fill capacity, verify new applications fail and page shows full.
6. Have a member exit; verify historic route changes remain, editor/group access is revoked, and capacity reopens.
7. Complete the plan; verify member can read historic messages but cannot send, and is itinerary read-only.
8. Check desktop/mobile focus states, no clipped bottom actions, and reduced-motion behavior.
```

- [ ] **Step 5: Commit operations and acceptance material**

```bash
git add frontend-b/src/features/admin/pages/OperationsPage.vue frontend-b/src/features/admin/services/operations.ts docs/API设计.md docs/本地验收使用手册.md docs/项目进度与完成度总结.md backend/tests/admin/test_companion_plan_admin.py
```

## Plan Self-Review

### Spec coverage

- Unified plan fields, business/review states, migration, and constraints: Task 1.
- Existing-itinerary and short-activity publishing: Tasks 2 and 7.
- Public discovery, privacy boundaries, details, filtering, and pagination: Tasks 3 and 6.
- Mandatory applications, atomic acceptance, capacity, blocks, group membership, itinerary editors, removal, exit, and completion: Task 4.
- Completed-group readable history and write restriction, plus Outbox-owned notifications: Task 5.
- Field / Travel visual language, responsive interaction, factual motion, reduced motion, and user states: Tasks 6 and 7.
- Admin moderation, documentation, migration lifecycle, focused tests, and browser acceptance: Task 8.

### Type consistency

- `CompanionPlanCreate` is the metadata body for existing itinerary plans; `CompanionActivityCreate` adds the verified one-day activity facts.
- `CompanionPlanSummary` is public; `CompanionPlanDetail` adds protected fields only for owner/accepted members.
- `conversation_id` is persisted on both plan and accepted application; the consumer navigates through it to `/messages/{conversation_id}`.
- `party_size` includes the owner, `accepted_count` begins at 1, and only `accepted_count == party_size` produces `status="full"`.

### Scope check

This plan is one coherent companion-plan capability. Future features such as identity verification, payment splitting, member voting, waitlists, and full product-wide visual redesign remain out of scope.
