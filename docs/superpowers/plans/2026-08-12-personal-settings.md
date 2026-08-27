# Personal Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent consumer personal settings center for account data, travel preferences, notifications, and profile visibility, and apply travel defaults to new AI planning requests.

**Architecture:** Store settings in a one-to-one `user_settings` SQLAlchemy model with a get-or-create settings service, exposed through authenticated `GET/PATCH /users/me/settings` endpoints. The backend merges saved travel defaults into a new generation request only when the request omitted the relevant field; the frontend makes overrides explicit and renders `/me/settings` as independently saved account, travel, notification, and privacy sections.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, Alembic/MySQL, Vue 3 Composition API, Pinia, Vue Router, Vitest, vue-tsc, Element Plus, Lucide.

## Global Constraints

- Do not modify `frontend-b`.
- Do not modify the existing `/auth/me` or `PATCH /users/me` response contracts.
- Keep phone numbers private from all consumer-facing profile serialization.
- Use one `user_settings` row per user, keyed by `user_id`.
- API updates are partial: only supplied fields change, and each response returns the complete normalized settings object.
- Defaults are `budget_level=balanced`, `travel_pace=balanced`, `traveler_type=friends`, empty `interest_tags`/`departure_city`, all notification switches enabled, and `profile_visibility=collaborators`.
- Settings vocabulary: `economy|balanced|premium`, `relaxed|balanced|packed`, `solo|couple|friends|family`, and `private|collaborators`.
- Existing AI contract vocabulary remains `pace=slow|balanced|fast`; map saved `relaxed` to `slow` and `packed` to `fast` at the service boundary.
- Never synthesize a numeric `budget_amount` from `budget_level`.
- Explicit generation request values, including intentionally empty lists and null optional values, override saved settings.
- All schema changes require a new Alembic revision and `upgrade head`, `downgrade -1`, `upgrade head` verification against MySQL.
- Use CodeGraph before discovery reads; when its staleness banner names a file, read that specific live file before editing.

---

## File Structure

### Backend persistence and settings API

- Modify: `backend/app/models/user.py` - add the `UserSettings` SQLAlchemy one-to-one model and constrained enum values.
- Create: `backend/alembic/versions/20260812_0039_user_settings.py` - create and reverse the `user_settings` table using MySQL-safe constraints.
- Modify: `backend/alembic/env.py` - imports the model module only if `UserSettings` lives outside `app.models.user`; no new import is needed when it remains in `user.py`.
- Modify: `backend/app/modules/users/schemas.py` - define settings read and partial-update Pydantic schemas plus controlled tag literals.
- Modify: `backend/app/modules/users/router.py` - expose the authenticated settings read/update endpoints.
- Create: `backend/tests/users/test_settings_router.py` - endpoint, defaults, partial-update, validation, and isolation coverage.
- Create: `backend/tests/models/test_user_settings.py` - model constraints/defaults coverage where the repository's test conventions make unit coverage appropriate.

### AI preference merge

- Modify: `backend/app/modules/ai_workflows/schemas.py` - make preference-bearing request fields distinguish omitted values from explicit values, while adding optional context fields needed by the workflow snapshot.
- Modify: `backend/app/modules/ai_workflows/router.py` - load the caller's settings and create an effective request before `GenerationJobService.create`.
- Modify: `backend/app/modules/ai_workflows/service.py` - persist only the effective request snapshot and preserve idempotency behavior.
- Modify: `backend/tests/ai_workflows/test_job_service.py` - cover effective request snapshots and no fabricated budget amount.
- Create: `backend/tests/ai_workflows/test_settings_defaults.py` - cover omitted versus explicit generation preference precedence at the route/service boundary.

### Notification and profile visibility integration

- Modify: `backend/app/workers/domain_handlers.py` - gate worker-created notification projections by settings master/category switches through its existing `_notify_user` handler.
- Modify: `backend/app/modules/community/service.py` - apply visibility to the existing authorized companion-member response serializer.
- Modify: `backend/app/modules/community/schemas.py` - permit hidden companion members to carry a null display name.
- Modify: `backend/tests/notifications/test_service.py`, `backend/tests/workers/test_companion_notifications.py`, and `backend/tests/community/test_companion_plans.py` - prove allowed/blocked output and notification suppression.

### Consumer settings surface

- Create: `frontend-c/src/features/settings/api.ts` - typed API client, frontend enums, and settings constants.
- Create: `frontend-c/src/features/settings/api.test.ts` - request/response and PATCH payload tests.
- Create: `frontend-c/src/features/settings/SettingsPage.vue` - grouped settings UI, per-section dirty/saving/error/success state, profile integration, and unsaved-change guard.
- Create: `frontend-c/src/features/settings/SettingsPage.test.ts` - user-facing settings state coverage.
- Modify: `frontend-c/src/router/index.ts` - add `/me/settings`; redirect `/me/profile` to `/me/settings#profile` without weakening consumer guard behavior.
- Modify: `frontend-c/src/App.vue` - link the authenticated account control and mobile navigation to settings.
- Modify: `frontend-c/src/features/profile/ProfilePage.vue` - replace the duplicate editable page with a compatible redirect/link surface, or remove the route component after the router redirect is verified.

### Consumer planning integration

- Modify: `frontend-c/src/features/itineraries/aiPlanningApi.ts` - extend only the typed request fields accepted by the backend and preserve request typing.
- Modify: `frontend-c/src/features/itineraries/stores/aiPlanning.ts` - preserve explicit optional values in `lastRequest` and retry requests.
- Modify: `frontend-c/src/features/itineraries/pages/PlanPage.vue` - load settings defaults, label/default controls, let current form values override or clear defaults, and submit explicit inputs.
- Modify: `frontend-c/src/features/ai/pages/AiAssistantPage.vue` - load settings defaults when creating an itinerary-modification preview and submit the effective local override fields.
- Modify: `frontend-c/src/features/itineraries/pages/PlanPage.test.ts` - settings default and explicit override/clear behavior.
- Modify: `frontend-c/src/features/itineraries/stores/aiPlanning.test.ts` - retry preserves the normalized request contract.

## Task 1: Persist User Settings With a Reversible Migration

**Files:**
- Modify: `backend/app/models/user.py:1-59`
- Create: `backend/alembic/versions/20260812_0039_user_settings.py`
- Test: `backend/tests/users/test_settings_router.py`

**Interfaces:**
- Consumes: `User`, `Base`, `UTCDateTime`, `UUIDPrimaryKeyMixin`, and `utc_now` from `app.models.user` / `app.models.base`.
- Produces: `UserSettings` with `user_id`, `departure_city`, `budget_level`, `travel_pace`, `interest_tags`, `traveler_type`, notification booleans, `profile_visibility`, `created_at`, and `updated_at`.

- [ ] **Step 1: Write model/default assertions before adding the model**

```python
def test_user_settings_defaults_are_product_defaults() -> None:
    settings = UserSettings(user_id="user-1")

    assert settings.budget_level == "balanced"
    assert settings.travel_pace == "balanced"
    assert settings.traveler_type == "friends"
    assert settings.interest_tags == []
    assert settings.notifications_enabled is True
    assert settings.profile_visibility == "collaborators"
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd backend && pytest tests/users/test_settings_router.py -k defaults -v`

Expected: FAIL because `UserSettings` does not exist.

- [ ] **Step 3: Add the one-to-one SQLAlchemy model**

```python
class UserSettings(Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("budget_level IN ('economy', 'balanced', 'premium')", name="ck_user_settings_budget_level"),
        CheckConstraint("travel_pace IN ('relaxed', 'balanced', 'packed')", name="ck_user_settings_travel_pace"),
        CheckConstraint("traveler_type IN ('solo', 'couple', 'friends', 'family')", name="ck_user_settings_traveler_type"),
        CheckConstraint("profile_visibility IN ('private', 'collaborators')", name="ck_user_settings_profile_visibility"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    departure_city: Mapped[str | None] = mapped_column(String(128))
    budget_level: Mapped[str] = mapped_column(String(16), nullable=False, default="balanced")
    travel_pace: Mapped[str] = mapped_column(String(16), nullable=False, default="balanced")
    interest_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    traveler_type: Mapped[str] = mapped_column(String(16), nullable=False, default="friends")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    order_notifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    itinerary_notifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    community_notifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    profile_visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="collaborators")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)
```

Import `Boolean` and `JSON` from SQLAlchemy. Keep the model in `app.models.user` so Alembic already sees it through the existing import in `alembic/env.py`.

- [ ] **Step 4: Create the revision from the current head `20260812_0038`**

```python
revision = "20260812_0039"
down_revision = "20260812_0038"

def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.String(36), primary_key=True, nullable=False),
        # Repeat every model column with matching server defaults.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("budget_level IN ('economy', 'balanced', 'premium')", name="ck_user_settings_budget_level"),
    )

def downgrade() -> None:
    op.drop_table("user_settings")
```

Use `mysql.JSON()` for `interest_tags`; make every persisted default a server default in the migration so a direct database insert produces the same settings defaults.

- [ ] **Step 5: Run the focused test and migration cycle**

Run: `cd backend && pytest tests/users/test_settings_router.py -k defaults -v`

Expected: PASS.

Run: `cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head`

Expected: all three commands complete against Compose MySQL.

- [ ] **Step 6: Commit the persistence layer**

```bash
git add backend/app/models/user.py backend/alembic/versions/20260812_0039_user_settings.py backend/tests/users/test_settings_router.py
```

## Task 2: Expose Typed Settings Read and Partial Update APIs

**Files:**
- Modify: `backend/app/modules/users/schemas.py:1-13`
- Modify: `backend/app/modules/users/router.py:1-45`
- Modify: `backend/app/api/router.py:1-63` only if the users router remains accidentally included twice after reconciling concurrent changes
- Test: `backend/tests/users/test_settings_router.py`

**Interfaces:**
- Consumes: `UserSettings` from `app.models.user`, `CurrentConsumer`, and async `Session`.
- Produces: `SettingsResponse` and `SettingsUpdateRequest`; `GET/PATCH /api/v1/users/me/settings`.

- [ ] **Step 1: Add failing endpoint tests**

```python
async def test_get_settings_creates_and_returns_defaults(client, consumer_headers, user):
    response = await client.get("/api/v1/users/me/settings", headers=consumer_headers(user))

    assert response.status_code == 200
    assert response.json()["budget_level"] == "balanced"
    assert response.json()["interest_tags"] == []

async def test_patch_settings_preserves_omitted_values(client, consumer_headers, user):
    first = await client.patch(
        "/api/v1/users/me/settings",
        headers=consumer_headers(user),
        json={"departure_city": "杭州", "travel_pace": "relaxed"},
    )
    second = await client.patch(
        "/api/v1/users/me/settings",
        headers=consumer_headers(user),
        json={"community_notifications": False},
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["departure_city"] == "杭州"
    assert second.json()["travel_pace"] == "relaxed"
    assert second.json()["community_notifications"] is False
```

Add tests for invalid tag, duplicate tags, invalid enum, empty PATCH body, and a second user who cannot observe or update the first user's values.

- [ ] **Step 2: Run the endpoint tests to verify they fail**

Run: `cd backend && pytest tests/users/test_settings_router.py -v`

Expected: FAIL with `404` because settings routes do not yet exist.

- [ ] **Step 3: Define Pydantic request and response schemas**

```python
InterestTag = Literal["经典必玩", "吃吃喝喝", "小众探索", "拍照出片", "逛街购物", "citywalk", "自然风光", "文艺展览", "历史古建"]

class SettingsUpdateRequest(BaseModel):
    departure_city: str | None = Field(default=None, max_length=128)
    budget_level: Literal["economy", "balanced", "premium"] | None = None
    travel_pace: Literal["relaxed", "balanced", "packed"] | None = None
    interest_tags: list[InterestTag] | None = Field(default=None, max_length=9)
    traveler_type: Literal["solo", "couple", "friends", "family"] | None = None
    notifications_enabled: bool | None = None
    order_notifications: bool | None = None
    itinerary_notifications: bool | None = None
    community_notifications: bool | None = None
    profile_visibility: Literal["private", "collaborators"] | None = None

    @field_validator("interest_tags")
    @classmethod
    def unique_tags(cls, value: list[InterestTag] | None) -> list[InterestTag] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("interest_tags must not contain duplicates.")
        return value
```

Use `model_fields_set` in the router so `null`, an empty string after normalization, and `[]` have distinct intentional PATCH behavior.

- [ ] **Step 4: Implement get-or-create and partial update handlers**

```python
async def _settings(session: AsyncSession, user_id: str) -> UserSettings:
    settings = await session.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id)
        session.add(settings)
        await session.flush()
    return settings

@router.get("/me/settings", response_model=SettingsResponse)
async def get_settings(claims: CurrentConsumer, session: Session) -> SettingsResponse:
    settings = await _settings(session, claims.user_id)
    await session.commit()
    return SettingsResponse.model_validate(settings)

@router.patch("/me/settings", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdateRequest, claims: CurrentConsumer, session: Session) -> SettingsResponse:
    if not body.model_fields_set:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "At least one settings field is required."})
    settings = await _settings(session, claims.user_id)
    for field_name in body.model_fields_set:
        setattr(settings, field_name, getattr(body, field_name))
    await session.commit()
    await session.refresh(settings)
    return SettingsResponse.model_validate(settings)
```

Normalize `departure_city` with `strip()` and store `None` for an explicitly blank string.

- [ ] **Step 5: Run focused router tests**

Run: `cd backend && pytest tests/users/test_settings_router.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the API contract**

```bash
git add backend/app/modules/users/schemas.py backend/app/modules/users/router.py backend/tests/users/test_settings_router.py
```

## Task 3: Apply Saved Preferences to New Generation Jobs

**Files:**
- Modify: `backend/app/modules/ai_workflows/schemas.py:38-77`
- Modify: `backend/app/modules/ai_workflows/router.py:1-36`
- Modify: `backend/app/modules/ai_workflows/service.py:46-129,289-293`
- Test: `backend/tests/ai_workflows/test_settings_defaults.py`
- Test: `backend/tests/ai_workflows/test_job_service.py`

**Interfaces:**
- Consumes: `UserSettings`, `GenerationJobCreate`, `GenerationJobService.create(user_id, idempotency_key, body)`.
- Produces: an effective `GenerationJobCreate` that has saved defaults only for omitted fields; persisted `GenerationJob.request_json` includes `budget_level`, `traveler_type`, and an effective source snapshot.

- [ ] **Step 1: Write precedence tests before changing request schemas**

```python
async def test_omitted_generation_preferences_use_saved_settings(client, consumer_headers, user, settings, destination):
    settings.travel_pace = "relaxed"
    settings.interest_tags = ["吃吃喝喝"]
    settings.budget_level = "premium"
    await session.commit()

    response = await client.post(
        "/api/v1/generation-jobs",
        headers={**consumer_headers(user), "Idempotency-Key": "settings-defaults"},
        json={"destination": destination, "start_date": "2026-10-01", "end_date": "2026-10-03", "prompt": ""},
    )

    assert response.status_code == 201
    job = await session.get(GenerationJob, response.json()["id"])
    assert job.request_json["pace"] == "slow"
    assert job.request_json["preference_tags"] == ["吃吃喝喝"]
    assert job.request_json["budget_level"] == "premium"
    assert job.request_json["budget_amount"] is None

async def test_explicit_empty_tags_and_explicit_pace_override_saved_settings(client, consumer_headers, user, settings, destination, session):
    settings.interest_tags = ["吃吃喝喝"]
    settings.travel_pace = "relaxed"
    await session.commit()

    response = await client.post(
        "/api/v1/generation-jobs",
        headers={**consumer_headers(user), "Idempotency-Key": "settings-explicit-overrides"},
        json={"destination": destination, "start_date": "2026-10-01", "end_date": "2026-10-03", "prompt": "", "preference_tags": [], "pace": "fast"},
    )

    job = await session.get(GenerationJob, response.json()["id"])
    assert job.request_json["preference_tags"] == []
    assert job.request_json["pace"] == "fast"
```

Add a target-itinerary test showing that existing itinerary modification requests do not inherit destination-dependent saved defaults unless the request omitted a compatible field.

- [ ] **Step 2: Run the precedence tests to verify they fail**

Run: `cd backend && pytest tests/ai_workflows/test_settings_defaults.py -v`

Expected: FAIL because the current request schema supplies defaults before the router can distinguish omission.

- [ ] **Step 3: Make omitted generation fields observable and normalize settings values**

Change the request schema fields that can inherit defaults to `None` defaults, then apply generation defaults only after merging:

```python
class GenerationJobCreate(BaseModel):
    preference_tags: list[PreferenceTag] | None = Field(default=None, max_length=3)
    pace: Literal["slow", "balanced", "fast"] | None = None
    budget_amount: int | None = Field(default=None, ge=0)
    budget_level: Literal["economy", "balanced", "premium"] | None = None
    traveler_type: Literal["solo", "couple", "friends", "family"] | None = None

def settings_pace_to_generation_pace(value: str) -> Literal["slow", "balanced", "fast"]:
    return {"relaxed": "slow", "balanced": "balanced", "packed": "fast"}[value]
```

Update validators and workflow consumers to use `body.preference_tags or []` only after the effective request is built, so explicit `[]` remains an override and omitted `None` can inherit.

- [ ] **Step 4: Merge settings in the router before service creation**

```python
async def _effective_generation_request(
    session: AsyncSession, user_id: str, body: GenerationJobCreate
) -> GenerationJobCreate:
    settings = await _settings(session, user_id)
    updates: dict[str, object] = {}
    if "preference_tags" not in body.model_fields_set:
        updates["preference_tags"] = settings.interest_tags[:3]
    if "pace" not in body.model_fields_set:
        updates["pace"] = settings_pace_to_generation_pace(settings.travel_pace)
    if "budget_level" not in body.model_fields_set:
        updates["budget_level"] = settings.budget_level
    if "traveler_type" not in body.model_fields_set:
        updates["traveler_type"] = settings.traveler_type
    return body.model_copy(update=updates)
```

Do not infer `budget_amount`. Do not replace explicit values, `[]`, or `null` values. Keep departure city out of a canonical destination request because destination resolution remains the existing selected-destination flow.

- [ ] **Step 5: Persist a complete effective request snapshot and update worker consumers**

```python
@staticmethod
def _request_snapshot(body: GenerationJobCreate, city_code: str) -> dict[str, object]:
    snapshot = body.model_dump(mode="json", exclude_none=False)
    snapshot["preference_tags"] = snapshot["preference_tags"] or []
    snapshot["pace"] = snapshot["pace"] or "balanced"
    snapshot["city_code"] = city_code
    return snapshot
```

Update every consumer of `request_json["preference_tags"]` and `request_json["pace"]` to rely on the normalized snapshot rather than nullable body properties.

- [ ] **Step 6: Run AI workflow tests**

Run: `cd backend && pytest tests/ai_workflows/test_settings_defaults.py tests/ai_workflows/test_job_service.py -v`

Expected: PASS.

- [ ] **Step 7: Commit AI default integration**

```bash
git add backend/app/modules/ai_workflows/schemas.py backend/app/modules/ai_workflows/router.py backend/app/modules/ai_workflows/service.py backend/tests/ai_workflows/test_settings_defaults.py backend/tests/ai_workflows/test_job_service.py
```

## Task 4: Enforce Notification Categories and Profile Visibility

**Files:**
- Modify: `backend/app/workers/domain_handlers.py:95-132`
- Modify: `backend/app/modules/community/service.py:502-585`
- Modify: `backend/app/modules/community/schemas.py:162-169`
- Test: `backend/tests/notifications/test_service.py`
- Test: `backend/tests/workers/test_companion_notifications.py`
- Test: `backend/tests/community/test_companion_plans.py`

**Interfaces:**
- Consumes: `UserSettings`, `Notification`, domain event types, `CommunityService._companion_members(plan, viewer_id)`, and `CompanionPlanMemberResponse`.
- Produces: category-aware notification projection suppression and visibility-filtered companion-member profile fields.

- [ ] **Step 1: Write failing category and visibility tests**

```python
async def test_master_notification_switch_suppresses_worker_notification(session, event, user, settings):
    settings.notifications_enabled = False
    await session.commit()

    await _notify_user(session, event_for("companion_application.accepted", applicant_id=user.id))

    assert await session.scalar(select(Notification).where(Notification.user_id == user.id)) is None

async def test_private_member_hides_profile_from_another_authorized_companion(session, private_member, owner, plan):
    session.add(UserSettings(user_id=private_member.id, profile_visibility="private"))
    await session.flush()
    detail = await CommunityService(session).get_companion_plan_detail(plan.id, owner.id)

    member = next(item for item in detail.members if item.role == "member")
    assert member.display_name is None
    assert member.avatar_asset_id is None
```

Add tests proving that a member can still see their own identity, that `collaborators` exposes another accepted member's identity, and that order, itinerary, and community event names choose the expected notification category.

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `cd backend && pytest tests/notifications/test_service.py -k settings -v`

Expected: FAIL because `_notify_user` writes notification rows without inspecting `UserSettings`, and `_companion_members` always exposes user identity.

- [ ] **Step 3: Add a deterministic category gate in the worker projection**

```python
def notification_category(event_type: str) -> str:
    if event_type.startswith(("travel_order.", "payment.", "fulfillment.", "refund.")):
        return "order"
    if event_type.startswith(("itinerary.", "route_calculation.", "ai.generation_")):
        return "itinerary"
    return "community"

async def _notification_enabled(session: AsyncSession, user_id: str, category: str) -> bool:
    settings = await session.get(UserSettings, user_id)
    if settings is None:
        return True
    return settings.notifications_enabled and bool(getattr(settings, f"{category}_notifications"))
```

Call `_notification_enabled()` from `_notify_user()` before it adds each existing `Notification`; keep the event payload and transaction semantics unchanged.

- [ ] **Step 4: Apply privacy to authorized companion member detail only**

```python
def _visible_member_profile(settings: UserSettings | None, *, viewer_id: str, member_id: str, nickname: str | None, avatar_asset_id: str | None) -> tuple[str | None, str | None]:
    if viewer_id == member_id:
        return nickname, avatar_asset_id
    if settings is None or settings.profile_visibility == "private":
        return None, None
    if settings.profile_visibility == "collaborators":
        return nickname, avatar_asset_id
    return None, None
```

Change `_companion_members` to accept `viewer_id`, bulk-load `UserSettings` by member ID, and call this helper. Pass `viewer_id` from `get_companion_plan_detail` only after its existing `is_member` authorization check. Change `CompanionPlanMemberResponse.display_name` to `str | None`; phone is not in this schema and must not be added.

- [ ] **Step 5: Run affected tests and inspect blast radius**

Run: `cd backend && pytest tests/notifications/test_service.py tests/workers/test_companion_notifications.py tests/community/test_companion_plans.py -v`

Run: `git diff --name-only | codegraph affected --stdin`

Expected: settings tests and all affected regression tests pass.

- [ ] **Step 6: Commit notification and privacy enforcement**

```bash
git add backend/app/workers/domain_handlers.py backend/app/modules/community/service.py backend/app/modules/community/schemas.py backend/tests/notifications/test_service.py backend/tests/workers/test_companion_notifications.py backend/tests/community/test_companion_plans.py
```

Stage only files actually changed in this task; do not stage concurrent, unrelated work.

## Task 5: Build the Settings API Client and Route Entry Points

**Files:**
- Create: `frontend-c/src/features/settings/api.ts`
- Create: `frontend-c/src/features/settings/api.test.ts`
- Modify: `frontend-c/src/router/index.ts:4-36`
- Modify: `frontend-c/src/App.vue:1-46`
- Modify: `frontend-c/src/features/profile/ProfilePage.vue`

**Interfaces:**
- Consumes: `GET/PATCH /users/me/settings`, existing profile API, Vue Router route guards, and `useAuthStore`.
- Produces: `UserSettings`, `SettingsUpdate`, `getMySettings()`, `updateMySettings(changes)`, and a guarded `/me/settings` route.

- [ ] **Step 1: Write API client and routing tests**

```typescript
it('sends a partial settings patch', async () => {
  mockedApi.patch.mockResolvedValue({ data: settingsFixture })

  await updateMySettings({ travel_pace: 'relaxed', interest_tags: ['吃吃喝喝'] })

  expect(mockedApi.patch).toHaveBeenCalledWith('/users/me/settings', {
    travel_pace: 'relaxed', interest_tags: ['吃吃喝喝'],
  })
})

it('guards the settings route for consumer sessions', async () => {
  const route = routes.find((entry) => entry.path === '/me/settings')
  expect(route?.meta).toMatchObject({ requiresConsumer: true })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend-c && npm run test -- src/features/settings/api.test.ts src/router/index.test.ts`

Expected: FAIL because the settings module and route do not exist.

- [ ] **Step 3: Implement typed settings API client**

```typescript
export type BudgetLevel = 'economy' | 'balanced' | 'premium'
export type TravelPace = 'relaxed' | 'balanced' | 'packed'
export type TravelerType = 'solo' | 'couple' | 'friends' | 'family'
export type ProfileVisibility = 'private' | 'collaborators'
export type InterestTag = '经典必玩' | '吃吃喝喝' | '小众探索' | '拍照出片' | '逛街购物' | 'citywalk' | '自然风光' | '文艺展览' | '历史古建'

export interface UserSettings {
  departure_city: string | null
  budget_level: BudgetLevel
  travel_pace: TravelPace
  interest_tags: InterestTag[]
  traveler_type: TravelerType
  notifications_enabled: boolean
  order_notifications: boolean
  itinerary_notifications: boolean
  community_notifications: boolean
  profile_visibility: ProfileVisibility
}

export function getMySettings() { return api.get<UserSettings>('/users/me/settings').then(({ data }) => data) }
export function updateMySettings(changes: Partial<UserSettings>) {
  return api.patch<UserSettings>('/users/me/settings', changes).then(({ data }) => data)
}
```

- [ ] **Step 4: Add navigation and compatibility routing**

```typescript
{ path: '/me/settings', component: () => import('@/features/settings/SettingsPage.vue'), meta: { requiresConsumer: true } },
{ path: '/me/profile', redirect: { path: '/me/settings', hash: '#profile' }, meta: { requiresConsumer: true } },
```

Add a `Settings` icon to authenticated navigation. Make the nickname/account control a `RouterLink` to `/me/settings`; keep logout as a separate icon button. Mobile navigation must contain the same settings entry.

- [ ] **Step 5: Replace the duplicate profile page safely**

Delete `ProfilePage.vue` only after test coverage confirms the compatibility redirect; otherwise retain a minimal page whose only action links to `/me/settings#profile`. Do not leave two independently editable profile forms.

- [ ] **Step 6: Run frontend API and router tests**

Run: `cd frontend-c && npm run test -- src/features/settings/api.test.ts src/router/index.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit client and entry points**

```bash
git add frontend-c/src/features/settings/api.ts frontend-c/src/features/settings/api.test.ts frontend-c/src/router/index.ts frontend-c/src/App.vue frontend-c/src/features/profile/ProfilePage.vue
```

## Task 6: Implement the Personal Settings Page

**Files:**
- Create: `frontend-c/src/features/settings/SettingsPage.vue`
- Create: `frontend-c/src/features/settings/SettingsPage.test.ts`
- Modify: `frontend-c/src/main.ts` only if an already-installed Element Plus component must be registered

**Interfaces:**
- Consumes: `getMyProfile`, `updateMyProfile`, `getMySettings`, `updateMySettings`, `uploadPrivateImage`, `getPrivateImageUrl`.
- Produces: `/me/settings` UI with account profile, travel preferences, notifications, privacy, per-section persistence, and dirty-navigation protection.

- [ ] **Step 1: Write failing component tests for each required state**

```typescript
it('loads profile and settings into separate editable sections', async () => {
  mockedGetMyProfile.mockResolvedValue(profileFixture)
  mockedGetMySettings.mockResolvedValue(settingsFixture)

  const wrapper = mount(SettingsPage)
  await flushPromises()

  expect(wrapper.get('[data-testid="settings-profile"]').text()).toContain('账户资料')
  expect(wrapper.get('[data-testid="settings-travel"]').text()).toContain('旅行偏好')
  expect(wrapper.get('input[name="departure-city"]').element.value).toBe('杭州')
})

it('keeps local edits and exposes the API error after a section save fails', async () => {
  mockedUpdateMySettings.mockRejectedValue(new Error('保存失败'))
  const wrapper = await mountLoadedSettingsPage()

  await wrapper.get('input[name="departure-city"]').setValue('上海')
  await wrapper.get('[data-testid="save-travel"]').trigger('click')

  expect(wrapper.get('input[name="departure-city"]').element.value).toBe('上海')
  expect(wrapper.text()).toContain('保存失败')
})
```

Add tests for per-section disablement, master notification switch disabling category controls visually without erasing values, privacy radio/segmented control, profile save, and `beforeunload`/route-leave confirmation when dirty.

- [ ] **Step 2: Run the component tests to verify they fail**

Run: `cd frontend-c && npm run test -- src/features/settings/SettingsPage.test.ts`

Expected: FAIL because `SettingsPage.vue` does not exist.

- [ ] **Step 3: Implement state loading and dirty tracking**

```typescript
const profile = ref<Profile | null>(null)
const settings = ref<UserSettings | null>(null)
const profileDraft = reactive({ nickname: '' })
const travelDraft = reactive({ departure_city: '', budget_level: 'balanced' as BudgetLevel, travel_pace: 'balanced' as TravelPace, interest_tags: [] as InterestTag[], traveler_type: 'friends' as TravelerType })
const notificationDraft = reactive({ notifications_enabled: true, order_notifications: true, itinerary_notifications: true, community_notifications: true })
const privacyDraft = reactive({ profile_visibility: 'collaborators' as ProfileVisibility })

const dirty = computed(() => profileDirty.value || travelDirty.value || notificationDirty.value || privacyDirty.value)

onBeforeRouteLeave(() => dirty.value ? window.confirm('有未保存的设置，确定离开吗？') : true)
```

Load profile and settings concurrently. Copy normalized server data into each draft after successful load and after that group saves. Do not mutate the response object directly as the editable form state.

- [ ] **Step 4: Implement grouped UI and persistence behavior**

Create four semantic `<section>` blocks with stable test IDs:

```vue
<section id="profile" data-testid="settings-profile">...</section>
<section data-testid="settings-travel">...</section>
<section data-testid="settings-notifications">...</section>
<section data-testid="settings-privacy">...</section>
```

For each group, provide a distinct `saveProfile`, `saveTravel`, `saveNotifications`, or `savePrivacy` handler. Each handler must call only its intended endpoint and partial payload. While saving a group, disable only its controls and save action. On failure, retain drafts; on success, replace the corresponding draft with normalized response data and show a scoped status message.

Use `<input type="checkbox">` for booleans, labeled native radio controls or an accessible segmented group for enums, and toggle buttons with `aria-pressed` for interest tags. Use icon buttons only where Lucide has a familiar action icon. Do not put a text-only icon substitute in buttons.

- [ ] **Step 5: Implement responsive and accessibility details**

Use an unframed page layout with a left section index at desktop widths and a single-column section stack below `768px`. Put labels above every input. Preserve visible `:focus-visible` states, status regions with `role="status"`, errors with `role="alert"`, skeleton loading shapes, and no horizontal overflow at mobile widths.

- [ ] **Step 6: Run page tests and typecheck**

Run: `cd frontend-c && npm run test -- src/features/settings/SettingsPage.test.ts`

Expected: PASS.

Run: `cd frontend-c && npm run typecheck`

Expected: PASS.

- [ ] **Step 7: Commit settings UI**

```bash
git add frontend-c/src/features/settings/SettingsPage.vue frontend-c/src/features/settings/SettingsPage.test.ts frontend-c/src/main.ts
```

## Task 7: Surface and Override Preferences in Consumer AI Planning

**Files:**
- Modify: `frontend-c/src/features/itineraries/aiPlanningApi.ts:37-80`
- Modify: `frontend-c/src/features/itineraries/stores/aiPlanning.ts:141-182`
- Modify: `frontend-c/src/features/itineraries/pages/PlanPage.vue:1-219`
- Modify: `frontend-c/src/features/ai/pages/AiAssistantPage.vue:1-145`
- Modify: `frontend-c/src/features/itineraries/pages/PlanPage.test.ts`
- Modify: `frontend-c/src/features/itineraries/stores/aiPlanning.test.ts`

**Interfaces:**
- Consumes: `getMySettings`, `UserSettings`, `SmartPlanRequest`, and backend optional generation fields.
- Produces: plan and assistant generation requests that omit untouched preference fields, send explicit choices/clears, and display saved-default provenance.

- [ ] **Step 1: Write failing planning behavior tests**

```typescript
it('submits saved tags only when the traveler did not edit tags in the plan', async () => {
  mockedGetMySettings.mockResolvedValue({ ...settingsFixture, interest_tags: ['吃吃喝喝'] })
  const wrapper = mount(PlanPage)
  await flushPromises()

  await submitValidPlan(wrapper)

  expect(mockedPlanningSubmit).toHaveBeenCalledWith(expect.objectContaining({ preference_tags: undefined }))
})

it('submits an explicit empty tag list after the traveler clears saved tags', async () => {
  const wrapper = await mountPlanWithSavedTag()
  await wrapper.get('[data-tag="吃吃喝喝"]').trigger('click')
  await submitValidPlan(wrapper)

  expect(mockedPlanningSubmit).toHaveBeenCalledWith(expect.objectContaining({ preference_tags: [] }))
})
```

Add equivalent tests for pace. Assert that a displayed default is not converted into a fake numeric budget amount.

- [ ] **Step 2: Run focused frontend planning tests to verify they fail**

Run: `cd frontend-c && npm run test -- src/features/itineraries/pages/PlanPage.test.ts src/features/itineraries/stores/aiPlanning.test.ts`

Expected: FAIL because planning does not load or track personal settings.

- [ ] **Step 3: Extend the frontend request type without adding client-side merging**

```typescript
export interface SmartPlanRequest {
  destination?: DestinationOption
  start_date: string
  end_date: string
  preference_tags?: PreferenceTag[]
  pace?: 'slow' | 'balanced' | 'fast' | null
  budget_level?: BudgetLevel | null
  traveler_type?: TravelerType | null
  prompt: string
  target_itinerary_id?: string | null
  base_version?: number | null
}
```

The frontend must use `undefined` for untouched fields so the backend applies saved defaults. It sends `[]` or `null` only when the user explicitly clears a default.

- [ ] **Step 4: Add plan-page preference provenance and override tracking**

```typescript
const savedSettings = ref<UserSettings | null>(null)
const tagsTouched = ref(false)
const paceTouched = ref(false)

function requestPreferences() {
  return {
    preference_tags: tagsTouched.value ? [...selectedTags.value] : undefined,
    pace: paceTouched.value ? selectedPace.value : undefined,
    budget_level: budgetTouched.value ? selectedBudgetLevel.value : undefined,
    traveler_type: travelerTypeTouched.value ? selectedTravelerType.value : undefined,
  }
}
```

Render concise copy such as `默认使用个人设置，可在本次行程中调整` and let selected settings prefill visible controls. When the traveler changes a control, set its corresponding touched flag. Add an explicit clear control for defaults that must send `[]` or `null`.

- [ ] **Step 5: Apply the same omission/override rules to itinerary modification previews**

Load settings in `AiAssistantPage` with its existing parallel page data. When the traveler has not edited revision preferences, omit these fields. If the modification UI exposes a one-off change, send the explicit normalized value. Do not change regular chat request payloads in this task.

- [ ] **Step 6: Run focused tests, full C checks, and build**

Run: `cd frontend-c && npm run test -- src/features/itineraries/pages/PlanPage.test.ts src/features/itineraries/stores/aiPlanning.test.ts`

Expected: PASS.

Run: `cd frontend-c && npm run typecheck && npm run test && npm run build`

Expected: all commands PASS.

- [ ] **Step 7: Commit consumer planning integration**

```bash
git add frontend-c/src/features/itineraries/aiPlanningApi.ts frontend-c/src/features/itineraries/stores/aiPlanning.ts frontend-c/src/features/itineraries/pages/PlanPage.vue frontend-c/src/features/ai/pages/AiAssistantPage.vue frontend-c/src/features/itineraries/pages/PlanPage.test.ts frontend-c/src/features/itineraries/stores/aiPlanning.test.ts
```

## Task 8: Perform Cross-System Regression and Migration Acceptance

**Files:**
- Modify: `docs/API设计.md` - document the two settings endpoints and request/response field vocabulary.
- Modify: `docs/本地验收使用手册.md` - add a settings creation, save, AI default, and privacy/notification verification flow if this guide is still the active acceptance document.
- Test: all changed backend and frontend test suites.

**Interfaces:**
- Consumes: the complete persisted settings API, AI effective request behavior, notification category gate, and consumer settings UI.
- Produces: documented, verified feature acceptance across MySQL and the consumer frontend.

- [ ] **Step 1: Add contract assertions to API documentation**

Document the endpoints precisely:

```text
GET /api/v1/users/me/settings -> complete normalized UserSettings
PATCH /api/v1/users/me/settings -> partial update, complete normalized UserSettings
```

List every enum value, the first-read defaults, the master-notification semantics, and that `phone` is never public. Document that omitted generation fields use personal defaults while explicit request values override them.

- [ ] **Step 2: Run the backend targeted and complete regression suites**

Run: `cd backend && pytest tests/users/test_settings_router.py tests/ai_workflows/test_settings_defaults.py tests/notifications/test_service.py -v`

Expected: PASS.

Run: `cd backend && pytest`

Expected: PASS. If unrelated existing failures occur, record their exact test name and failure output separately; do not mask them.

- [ ] **Step 3: Verify the database migration round trip**

Run: `cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head`

Expected: `user_settings` is created, dropped, then recreated with defaults and constraints intact.

- [ ] **Step 4: Run consumer regression checks**

Run: `cd frontend-c && npm run typecheck && npm run test && npm run build`

Expected: all commands PASS.

- [ ] **Step 5: Run browser acceptance against a running C frontend**

Run: `cd frontend-c && npm run dev -- --port 5173`

Use the configured browser acceptance workflow to verify desktop and mobile views at `/me/settings`, account navigation, profile save, each settings group, an unsaved-change prompt, and `/plan` default/override messaging. Verify focus traversal and no clipped/overlapping controls at mobile width.

- [ ] **Step 6: Inspect CodeGraph impact and final diff**

Run: `git diff --name-only HEAD~1 | codegraph affected --stdin`

Run: `git diff --check`

Expected: affected tests have been run and no whitespace errors are present.

- [ ] **Step 7: Commit documentation and acceptance evidence**

```bash
git add docs/API设计.md docs/本地验收使用手册.md
```

Do not include generated build output, `.codegraph/`, local credentials, or unrelated concurrent changes.

## Plan Self-Review

### Spec coverage

- Account profile, read-only phone/user identity, setting navigation, and profile route compatibility are implemented in Tasks 5 and 6.
- Travel preferences and their direct AI planning effect are implemented in Tasks 3 and 7.
- Master/category notification controls are persisted in Tasks 1 and 2 and enforced in Task 4.
- `private`/`collaborators` visibility and non-public phone behavior are implemented in Task 4.
- Per-section save/error/loading/dirty states and responsive design are implemented and tested in Task 6.
- MySQL migration creation, rollback, and re-upgrade are verified in Tasks 1 and 8.
- Backend/frontend regression, browser acceptance, docs, and affected-test inspection are covered in Task 8.

### Placeholder scan

No implementation placeholders remain. Task 4 names the live worker notification projection and the only current consumer profile serializer, including concrete test files and function signatures.

### Type consistency

- Persisted settings use `travel_pace=relaxed|balanced|packed`; generation uses `pace=slow|balanced|fast` through the explicitly named mapping.
- `UserSettings` uses snake_case to match the FastAPI response and Vue API client.
- `SettingsUpdateRequest`, `SettingsResponse`, `getMySettings`, and `updateMySettings` are consistently named across backend and frontend tasks.
- Explicit request handling consistently uses `model_fields_set` on the backend and `undefined` versus `[]`/`null` on the frontend.
