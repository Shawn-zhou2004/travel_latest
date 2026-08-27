# Field Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing community post flow into a reviewed, photo-backed field-note community where published itinerary snapshots can be read, interacted with, and copied into independent editable itineraries.

**Architecture:** Keep `Post` as the only public-content aggregate and use `content_type="itinerary"` for field notes. The community service freezes a deliberately projected public version snapshot at submission time, while `ItineraryService` materializes a new itinerary from that immutable snapshot under an idempotency key. The Vue consumer app replaces the post dialog with a route-based reading experience and adds an itinerary-workspace publishing flow.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy async, Alembic/MySQL, pytest, Vue 3, TypeScript, Vite, Element Plus, lucide-vue-next.

## Global Constraints

- Keep `Post`, `PostMedia`, `Comment`, `PostReaction`, `PostFavorite`, and `ContentReport` as the only field-note content and interaction models.
- A field note has `content_type="itinerary"` and must freeze the selected `ItineraryVersion`; do not accept a client-provided snapshot as a source of truth.
- Public snapshots contain route-facing data only. They exclude private budgets, checklists, collaborators, share tokens, operation history, payment data, and non-selected media.
- A published field note must never change when its source itinerary later changes.
- Copying creates an itinerary owned only by the copying consumer, with fresh days and events. It cannot add the original author as a collaborator or mutate the source itinerary or post.
- `POST /posts/{post_id}:copy-itinerary` requires `Idempotency-Key`; retries return the original copy and must not increment `copy_count` twice.
- Only `published` field notes are public or copyable. Existing moderation, reporting, reactions, favorites, comments, search, and community knowledge-review behavior remains intact.
- First release supports JPEG, PNG, and WebP images only. Do not add video support.
- Preserve the Field / Travel palette: `#102B3A`, `#F3F7F5`, `#167A76`, `#D99824`, `#CE644E`; use no decorative gradients or excessive rounded-card layout.
- Run backend migration verification against Compose MySQL: `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head`.
- Run `npm run typecheck`, `npm run build`, focused pytest suites, and browser acceptance before declaring the feature complete.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/alembic/versions/20260812_0037_field_notes.py` | Add nullable field-note columns to `posts`, `itineraries.source_post_id`, durable copy idempotency facts, indexes, checks, and rollback. |
| `backend/app/modules/community/models.py` | Model immutable field-note data and post-to-media relation fields. |
| `backend/app/modules/community/schemas.py` | Define public feed/detail, creation, media, author-list, and copy response schemas. |
| `backend/app/modules/community/service.py` | Freeze version data, validate media, list/read field notes, and enforce publication state. |
| `backend/app/modules/community/router.py` | Expose field-note feed/detail/author routes and copy endpoint wiring. |
| `backend/app/modules/itineraries/models.py` | Add the source field and copy idempotency model for copied itineraries. |
| `backend/app/modules/itineraries/schemas.py` | Expose copied-from post metadata and accept an idempotency header result. |
| `backend/app/modules/itineraries/service.py` | Create independent itineraries from a validated field-note snapshot. |
| `backend/app/modules/itineraries/router.py` | Publish from workspace route and copy-operation endpoint dependency composition. |
| `backend/tests/community/test_services.py` | Unit-test freezing, media authorization, visibility, and public list behavior. |
| `backend/tests/community/test_router.py` | Integration-test publish/read/copy HTTP authorization and idempotency. |
| `backend/tests/itineraries/test_services.py` | Test fresh-id snapshot materialization and copy-source relation. |
| `frontend-c/src/features/community/fieldNotesApi.ts` | Typed field-note API client and API-facing models. |
| `frontend-c/src/features/community/FieldNotesPage.vue` | Editorial field-note feed, query controls, loading/error/empty states. |
| `frontend-c/src/features/community/FieldNoteDetailPage.vue` | Route-based reader, gallery, day timeline, interactions, comments, and copy action. |
| `frontend-c/src/features/community/FieldNotePublishPage.vue` | Read-only version preview, recap and image composition, submission state. |
| `frontend-c/src/features/community/components/FieldNoteCard.vue` | Reusable route-summary card for featured and ordinary feed items. |
| `frontend-c/src/features/community/components/FieldNoteTimeline.vue` | Ordered public day/event rendering used by detail and publish preview. |
| `frontend-c/src/features/community/fieldNotes.test.ts` | Formatting/state and API-client tests. |
| `frontend-c/src/features/itineraries/api.ts` | Typed publish request, field-note source, and version snapshot client helpers. |
| `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue` | Owner/editor publish entry and copied-from source label. |
| `frontend-c/src/router/index.ts` | Add field-note detail and publish routes. |
| `frontend-c/src/App.vue` | Rename public navigation label to the final Chinese field-note label. |
| `docs/API设计.md` | Document field-note and copy contracts and public/private boundaries. |
| `docs/本地验收使用手册.md` | Add author, reviewer, reader, and copy acceptance steps. |

## Task 1: Persist Field-Note and Copy Facts

**Files:**
- Modify: `backend/app/modules/community/models.py`
- Modify: `backend/app/modules/itineraries/models.py`
- Create: `backend/alembic/versions/20260812_0037_field_notes.py`
- Modify: `backend/alembic/env.py` only if the existing explicit model import list does not already import both model modules.
- Test: `backend/tests/community/test_field_note_models.py`

**Interfaces:**
- Produces `Post.itinerary_id`, `Post.itinerary_version_id`, `Post.itinerary_snapshot_json`, `Post.recap_text`, `Post.cover_media_id`, and nonnegative `Post.copy_count`.
- Produces `Itinerary.source_post_id`, nullable and `ON DELETE SET NULL`.
- Produces `ItineraryCopyOperation` with a unique `(actor_id, source_post_id, idempotency_key)` boundary and a durable created itinerary reference.
- Existing `Post` rows remain valid with all new field-note columns nullable.

- [ ] **Step 1: Write failing metadata and constraint tests**

```python
def test_field_note_columns_allow_legacy_notes_and_require_nonnegative_copy_count():
    post = Post(author_id=user.id, content_type="note", title="Legacy", body_text="old")
    session.add(post)
    await session.commit()

    note = Post(
        author_id=user.id,
        content_type="itinerary",
        title="Hangzhou two days",
        itinerary_snapshot_json={"title": "Hangzhou", "days": []},
        recap_text="Walked before breakfast.",
        copy_count=-1,
    )
    session.add(note)
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: Run the new model test and verify it fails**

Run: `pytest tests/community/test_field_note_models.py -v`

Expected: failure because the new ORM columns and database check constraint do not exist.

- [ ] **Step 3: Add nullable ORM fields and the migration**

Implement columns and constraints with the following shape:

```python
# community/models.py
itinerary_id: Mapped[str | None] = mapped_column(
    ForeignKey("itineraries.id", ondelete="SET NULL"), index=True
)
itinerary_version_id: Mapped[str | None] = mapped_column(
    ForeignKey("itinerary_versions.id", ondelete="SET NULL"), index=True
)
itinerary_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
recap_text: Mapped[str | None] = mapped_column(Text)
cover_media_id: Mapped[str | None] = mapped_column(
    ForeignKey("media_assets.id", ondelete="SET NULL")
)
copy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

# itineraries/models.py
source_post_id: Mapped[str | None] = mapped_column(
    ForeignKey("posts.id", ondelete="SET NULL"), index=True
)

class ItineraryCopyOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "itinerary_copy_operations"
    __table_args__ = (UniqueConstraint("actor_id", "source_post_id", "idempotency_key", name="uq_itinerary_copy_operations_actor_source_key"),)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    itinerary_id: Mapped[str] = mapped_column(ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
```

Use `CheckConstraint("copy_count >= 0", name="ck_posts_copy_count_nonnegative")`. The Alembic revision must add fields and `itinerary_copy_operations` without a data backfill, add indexes for post itinerary lookup and copied-itinerary source lookup, and reverse every operation in `downgrade()`.

- [ ] **Step 4: Run metadata tests and migration lifecycle verification**

Run: `pytest tests/community/test_field_note_models.py -v`

Expected: PASS.

Run from `backend`: `alembic upgrade head; alembic downgrade -1; alembic upgrade head`

Expected: all three commands complete successfully against Compose MySQL.

- [ ] **Step 5: Commit the persistence boundary**

```bash
git add backend/app/modules/community/models.py backend/app/modules/itineraries/models.py backend/alembic/env.py backend/alembic/versions/20260812_0037_field_notes.py backend/tests/community/test_field_note_models.py
```

## Task 2: Freeze and Publish Trusted Field Notes

**Files:**
- Modify: `backend/app/modules/community/schemas.py`
- Modify: `backend/app/modules/community/service.py`
- Modify: `backend/app/modules/community/router.py`
- Test: `backend/tests/community/test_services.py`
- Test: `backend/tests/community/test_router.py`

**Interfaces:**
- Consumes an authenticated actor, itinerary ID, `version_no`, `title`, `recap_text`, `cover_media_id`, and ordered `media_ids`.
- Produces `CommunityService.create_field_note(...) -> Post` with `status="pending_review"`.
- Produces `FieldNoteResponse` with `recap_text`, `itinerary_snapshot`, `cover_media_id`, `media_ids`, `day_count`, `stop_count`, and `copy_count`.
- `POST /itineraries/{itinerary_id}/field-notes` is available to owners and accepted editors only.

- [ ] **Step 1: Write failing service tests for authorized snapshot freezing**

```python
@pytest.mark.anyio
async def test_editor_can_freeze_one_version_without_exposing_private_trip_data(session):
    post = await CommunityService(session).create_field_note(
        author_id=editor.id,
        itinerary_id=itinerary.id,
        version_no=1,
        title="West Lake slowly",
        recap_text="Go before the crowds arrive.",
        cover_media_id=image.id,
        media_ids=[image.id],
    )
    assert post.status == "pending_review"
    assert post.itinerary_snapshot_json == {
        "title": "West Lake",
        "start_date": "2026-10-01",
        "end_date": "2026-10-02",
        "days": expected_public_days,
    }
    assert "id" not in post.itinerary_snapshot_json["days"][0]
    assert "route_calculation" not in post.itinerary_snapshot_json["days"][0]

@pytest.mark.anyio
async def test_field_note_rejects_unowned_or_incomplete_media(session):
    with pytest.raises(CommunityError, match="FORBIDDEN"):
        await service.create_field_note(..., cover_media_id=other_users_image.id, media_ids=[other_users_image.id])
```

- [ ] **Step 2: Run the focused service tests and verify they fail**

Run: `pytest tests/community/test_services.py -k "field_note" -v`

Expected: failure because neither the method nor field-note schema exists.

- [ ] **Step 3: Add schemas, public projection, and media validation**

Define explicit request/response schemas:

```python
class FieldNoteCreate(BaseModel):
    version_no: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    recap_text: str = Field(min_length=1, max_length=20_000)
    cover_media_id: str
    media_ids: list[str] = Field(min_length=1, max_length=9)

class FieldNoteResponse(PostResponse):
    recap_text: str
    itinerary_snapshot: dict[str, Any]
    cover_media_id: str | None
    media_ids: list[str]
    day_count: int
    stop_count: int
    copy_count: int
```

In `CommunityService.create_field_note`, load the itinerary and validate owner or accepted editor; load the requested `ItineraryVersion`; load every `MediaAsset` and require `owner_id == author_id`, `status == "completed"`, and `mime_type in {"image/jpeg", "image/png", "image/webp"}`. Require `cover_media_id in media_ids`.

Create `_public_itinerary_snapshot(version.snapshot)` that emits only title, ISO dates, ordered `days`, day date/order, and ordered event `poi_id`, `poi_snapshot`, times, order, and notes. It must omit all persisted day/event IDs, route segments, route jobs, and non-route fields. Create the post with `content_type="itinerary"`, insert ordered `PostMedia` rows, and set it directly to `pending_review`; do not create a generic draft first.

- [ ] **Step 4: Add the authenticated publish route and HTTP tests**

Route implementation shape:

```python
@router.post("/{itinerary_id}/field-notes", response_model=FieldNoteResponse, status_code=201)
async def create_field_note(itinerary_id: str, body: FieldNoteCreate, claims: CurrentConsumer, session: Session):
    try:
        post = await CommunityService(session).create_field_note(claims.user_id, itinerary_id, **body.model_dump())
        await session.commit()
        return await CommunityService(session).field_note_response(post)
    except CommunityError as error:
        raise _error(error) from error
```

Test 201 for owner and accepted editor; test 403 for viewer/outsider; test 422 for missing itinerary events, mismatched cover ID, or invalid version; verify the public response contains no original internal IDs.

- [ ] **Step 5: Run focused publication tests**

Run: `pytest tests/community/test_services.py -k "field_note" -v; pytest tests/community/test_router.py -k "field_note" -v`

Expected: PASS.

- [ ] **Step 6: Commit field-note creation**

```bash
git add backend/app/modules/community/schemas.py backend/app/modules/community/service.py backend/app/modules/community/router.py backend/tests/community/test_services.py backend/tests/community/test_router.py
```

## Task 3: Read, Filter, and Copy Published Snapshots

**Files:**
- Modify: `backend/app/modules/community/schemas.py`
- Modify: `backend/app/modules/community/service.py`
- Modify: `backend/app/modules/community/router.py`
- Modify: `backend/app/modules/itineraries/schemas.py`
- Modify: `backend/app/modules/itineraries/service.py`
- Test: `backend/tests/community/test_services.py`
- Test: `backend/tests/community/test_router.py`
- Test: `backend/tests/itineraries/test_services.py`

**Interfaces:**
- `GET /posts?content_type=itinerary&city_code=&q=&sort=latest|recommended` returns only published field notes.
- `GET /posts/{post_id}` returns public field-note detail only when the post is published.
- `POST /posts/{post_id}:copy-itinerary` consumes `Idempotency-Key` and returns `{ itinerary: ItineraryResponse, source_post_id: str, idempotent: bool }`.
- `ItineraryService.copy_field_note(post, actor_id, idempotency_key)` creates a fresh aggregate and increments `copy_count` once.

- [ ] **Step 1: Write failing visibility, projection, and copy tests**

```python
@pytest.mark.anyio
async def test_public_feed_excludes_notes_and_unpublished_field_notes(session):
    items, _ = await service.list_field_notes(city_code="330100", query=None, sort="latest", limit=20, cursor=None)
    assert [item.id for item in items] == [published_field_note.id]

@pytest.mark.anyio
async def test_copy_creates_fresh_days_events_and_is_idempotent(session):
    first = await itinerary_service.copy_field_note(published_note, reader.id, "copy-key-1")
    second = await itinerary_service.copy_field_note(published_note, reader.id, "copy-key-1")
    assert first.itinerary.id == second.itinerary.id
    assert first.idempotent is False and second.idempotent is True
    assert first.itinerary.owner_id == reader.id
    assert first.itinerary.source_post_id == published_note.id
    assert copied_day.id != source_snapshot_day_id
    assert copied_event.id != source_snapshot_event_id
    assert published_note.copy_count == 1
```

- [ ] **Step 2: Run the read/copy tests and verify they fail**

Run: `pytest tests/community/test_services.py -k "field_note" -v; pytest tests/itineraries/test_services.py -k "copy_field_note" -v`

Expected: failure because the list/detail/copy interfaces do not yet exist.

- [ ] **Step 3: Implement response building and public discovery**

Implement `field_note_response(post)` to load ordered `PostMedia`, calculate `day_count` and `stop_count` from the frozen JSON, and return safe public data. Update `list_published_posts` to accept only explicit `content_type` filtering and delegate itinerary listing to `list_field_notes`; do not change existing default generic-post behavior unintentionally.

Implement `list_field_notes` with `Post.status == "published"`, `Post.content_type == "itinerary"`, optional exact city code, title/recap search, stable cursor ordering, and either `published_at DESC, id DESC` or recommended order `copy_count DESC, published_at DESC, id DESC`. `get_published_post` must return a field-note response for itinerary content and preserve existing `PostResponse` behavior for legacy notes.

- [ ] **Step 4: Implement copy materialization with a durable idempotency record**

Use the `ItineraryCopyOperation` table created in Task 1. Its unique `(actor_id, source_post_id, idempotency_key)` constraint stores the created itinerary ID. The service must lock or read the operation before creating data.

Implementation shape:

```python
async def copy_field_note(self, post: Post, actor_id: str, idempotency_key: str) -> FieldNoteCopyResult:
    existing = await self.session.scalar(select(ItineraryCopyOperation).where(
        ItineraryCopyOperation.actor_id == actor_id,
        ItineraryCopyOperation.source_post_id == post.id,
        ItineraryCopyOperation.idempotency_key == idempotency_key,
    ))
    if existing:
        return FieldNoteCopyResult(await self.session.get(Itinerary, existing.itinerary_id), True)
    snapshot = _validate_public_snapshot(post.itinerary_snapshot_json)
    itinerary = Itinerary(owner_id=actor_id, title=snapshot["title"], start_date=..., end_date=..., source_post_id=post.id)
    self.session.add(itinerary)
    await self.session.flush()
    await self._replace_snapshot(itinerary, snapshot)
    await self._record_version(itinerary, actor_id)
    self.session.add(ItineraryCopyOperation(...))
    post.copy_count += 1
    await self.session.commit()
    return FieldNoteCopyResult(itinerary, False)
```

Adapt `_replace_snapshot` or create a dedicated `_materialize_public_snapshot` so it accepts snapshots without persisted IDs and uses each day/event `display_order`. It must parse dates/timestamps, create new rows, and create neither `RouteSegment` nor `RouteCalculationJob` from public data. Validate snapshot types and nonempty day/event data before writes; return a domain error for malformed stored snapshots.

- [ ] **Step 5: Add copy endpoint and router assertions**

```python
@router.post("/{post_id}:copy-itinerary", response_model=FieldNoteCopyResponse, status_code=201)
async def copy_field_note(
    post_id: str,
    claims: CurrentConsumer,
    session: Session,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
):
    post = await CommunityService(session).get_published_field_note(post_id)
    result = await ItineraryService(session).copy_field_note(post, claims.user_id, idempotency_key)
    return FieldNoteCopyResponse(itinerary=ItineraryResponse.model_validate(result.itinerary), source_post_id=post.id, idempotent=result.idempotent)
```

Test unauthenticated `401`, hidden/pending `404`, first copy `201`, retry with same key and same returned itinerary ID, source count unchanged on retry, and a second key creating a second owned itinerary.

- [ ] **Step 6: Run focused domain and router suites**

Run: `pytest tests/community/test_services.py tests/community/test_router.py tests/itineraries/test_services.py -v`

Expected: PASS.

- [ ] **Step 7: Commit public reading and copying**

```bash
git add backend/app/modules/community backend/app/modules/itineraries backend/alembic/versions/20260812_0037_field_notes.py backend/tests/community backend/tests/itineraries/test_services.py
```

## Task 4: Add Typed Consumer Clients and Routes

**Files:**
- Create: `frontend-c/src/features/community/fieldNotesApi.ts`
- Create: `frontend-c/src/features/community/fieldNotes.test.ts`
- Modify: `frontend-c/src/features/itineraries/api.ts`
- Modify: `frontend-c/src/router/index.ts`
- Modify: `frontend-c/src/App.vue`

**Interfaces:**
- Produces `FieldNoteSummary`, `FieldNoteDetail`, `FieldNoteCopyResult`, and `FieldNotePublishRequest` TypeScript contracts matching backend schemas.
- Produces `listFieldNotes`, `getFieldNote`, `copyFieldNote`, `publishFieldNote`, and `listItineraryVersions` client methods.
- Adds `/community/:postId` and `/itineraries/:itineraryId/publish-field-note` routes.

- [ ] **Step 1: Write API-client and route tests first**

```ts
it('copies a published field note with an idempotency key', async () => {
  api.post.mockResolvedValue({ data: { itinerary: itinerary, source_post_id: 'post-1', idempotent: false } })
  await copyFieldNote('post-1')
  expect(api.post).toHaveBeenCalledWith('/posts/post-1:copy-itinerary', {}, {
    headers: { 'Idempotency-Key': expect.any(String) },
  })
})

it('registers public detail and authenticated publish routes', () => {
  expect(routes.map((route) => route.path)).toContain('/community/:postId')
  expect(routes.find((route) => route.path === '/itineraries/:itineraryId/publish-field-note')?.meta).toMatchObject({ requiresConsumer: true })
})
```

- [ ] **Step 2: Run frontend tests and verify failure**

Run from `frontend-c`: `npm run test -- fieldNotes.test.ts`

Expected: failure because the module and routes do not exist.

- [ ] **Step 3: Implement API contracts and routing**

Define types that use `ItinerarySnapshot` from the existing itinerary client rather than duplicating day/event shapes. `copyFieldNote` must generate `crypto.randomUUID()` per user action; it must accept an optional supplied key only for retry tests. `publishFieldNote` posts the explicitly selected version and image IDs to `/itineraries/${itineraryId}/field-notes`.

Add lazy routes:

```ts
{ path: '/community', component: () => import('@/features/community/FieldNotesPage.vue') },
{ path: '/community/:postId', component: () => import('@/features/community/FieldNoteDetailPage.vue'), props: true },
{ path: '/itineraries/:itineraryId/publish-field-note', component: () => import('@/features/community/FieldNotePublishPage.vue'), props: true, meta: { requiresConsumer: true } },
```

Change the navigation label from `Field notes` to `田野笔记`; preserve the existing `Newspaper` icon and public access.

- [ ] **Step 4: Run API-client and router tests**

Run: `npm run test -- fieldNotes.test.ts router/index.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit typed consumer integration**

```bash
git add frontend-c/src/features/community/fieldNotesApi.ts frontend-c/src/features/community/fieldNotes.test.ts frontend-c/src/features/itineraries/api.ts frontend-c/src/router/index.ts frontend-c/src/App.vue
```

## Task 5: Build the Field-Note Feed and Detail Reader

**Files:**
- Create: `frontend-c/src/features/community/components/FieldNoteCard.vue`
- Create: `frontend-c/src/features/community/components/FieldNoteTimeline.vue`
- Create: `frontend-c/src/features/community/FieldNotesPage.vue`
- Create: `frontend-c/src/features/community/FieldNoteDetailPage.vue`
- Modify: `frontend-c/src/features/community/fieldNotes.test.ts`

**Interfaces:**
- Consumes `FieldNoteSummary` and `FieldNoteDetail` from `fieldNotesApi.ts`.
- Emits no direct mutations from cards; navigation goes to the detail route.
- Detail's copy action creates a new itinerary then routes to `/itineraries/{id}`.

- [ ] **Step 1: Write deterministic view-model tests**

```ts
it('formats route metadata from the frozen snapshot', () => {
  expect(routeMeta({ days: [{ events: [{}, {}] }, { events: [{}] }] } as ItinerarySnapshot)).toEqual({ days: 2, stops: 3 })
})

it('uses the detail copy result route', () => {
  expect(copyDestination({ itinerary: { id: 'trip-2' } } as FieldNoteCopyResult)).toBe('/itineraries/trip-2')
})
```

- [ ] **Step 2: Run the view-model tests and verify failure**

Run: `npm run test -- fieldNotes.test.ts`

Expected: failure because the helpers and field-note components do not exist.

- [ ] **Step 3: Implement the editorial feed**

Build `FieldNotesPage.vue` as a real discovery surface, not the previous post editor/dialog. It must:

- Load `content_type=itinerary` content on mount and when applied filters change.
- Offer explicit keyword search, destination/city code filter, and `recommended`/`latest` segmented sorting.
- Render one featured first note and then `FieldNoteCard` entries in a responsive editorial grid.
- Give every card a visible cover, destination, days/stops, title, recap excerpt, author, interaction metrics, and a route to detail.
- Render loading skeletons, no-result reset action, and retryable API error.

Use the established Field colors; cards may frame individual repeated content but do not wrap whole sections in decorative cards. Provide `:focus-visible` outlines in saffron and remove nonessential motion under `prefers-reduced-motion`.

- [ ] **Step 4: Implement the route-based detail reader**

Build `FieldNoteDetailPage.vue` with public-read handling and authenticated conditional actions:

- Fetch note detail and comments independently; show unavailable state for a 404.
- Render cover, title, destination, author, route metadata, recap body with preserved line breaks, ordered gallery, and `FieldNoteTimeline` grouped by day.
- Desktop: use a sticky, unframed right action column. Mobile: create a stable bottom action bar.
- Copy is the primary coral action. On success, call `router.push(`/itineraries/${result.itinerary.id}`)`; on failure, preserve the detail page and show retryable error.
- Reuse current API endpoints for reactions, favorites, comments, and reports. Represent current controls with lucide icons and accessible labels/tooltips; do not show duplicate “like/unlike” controls simultaneously.
- For unlogged visitors, show read-only interaction affordances that route to login with the current detail URL as redirect.

- [ ] **Step 5: Run targeted frontend checks**

Run: `npm run test -- fieldNotes.test.ts`

Expected: PASS.

Run: `npm run typecheck`

Expected: PASS with no unresolved API types or template errors.

- [ ] **Step 6: Commit the field-note reader**

```bash
git add frontend-c/src/features/community/components/FieldNoteCard.vue frontend-c/src/features/community/components/FieldNoteTimeline.vue frontend-c/src/features/community/FieldNotesPage.vue frontend-c/src/features/community/FieldNoteDetailPage.vue frontend-c/src/features/community/fieldNotes.test.ts
```

## Task 6: Publish From the Itinerary Workspace

**Files:**
- Create: `frontend-c/src/features/community/FieldNotePublishPage.vue`
- Modify: `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue`
- Modify: `frontend-c/src/features/itineraries/api.ts`
- Modify: `frontend-c/src/features/community/fieldNotes.test.ts`

**Interfaces:**
- Consumes workspace `itineraryId`, accessible `ItineraryVersion[]`, full selected `ItineraryVersionDetail`, and `uploadPrivateImage(file, "field_note")`.
- Produces a submitted field note through `publishFieldNote(itineraryId, request)`.
- Exposes only owner/editor publishing; source labels render only when `ItineraryDetail.source_post_id` is populated.

- [ ] **Step 1: Write publish form behavior tests**

```ts
it('requires a selected version, recap, cover, and at least one uploaded image', () => {
  expect(canPublish({ versionNo: null, recap: 'Text', coverId: 'asset-1', mediaIds: ['asset-1'] })).toBe(false)
  expect(canPublish({ versionNo: 2, recap: 'Text', coverId: 'asset-1', mediaIds: ['asset-1'] })).toBe(true)
})

it('sends the selected immutable version rather than the live workspace snapshot', async () => {
  await submitFieldNote({ versionNo: 2, title: 'Quiet Hangzhou', recapText: '...', coverMediaId: 'asset-1', mediaIds: ['asset-1'] })
  expect(publishFieldNote).toHaveBeenCalledWith('trip-1', expect.objectContaining({ version_no: 2 }))
})
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `npm run test -- fieldNotes.test.ts`

Expected: failure because the publish page/helpers do not exist.

- [ ] **Step 3: Add workspace entry and publishing page**

In `ItineraryWorkspacePage.vue`, add a labeled action with an appropriate lucide publish/send icon for any `store.canEdit` itinerary. Do not hide it from accepted editors. It navigates to `/itineraries/${props.itineraryId}/publish-field-note`. When `getItinerary()` includes `source_post_id`, render a small source label with a link to `/community/${source_post_id}` near the title metadata.

`FieldNotePublishPage.vue` must load accessible versions, default to current version, fetch the selected detailed version, and display it through `FieldNoteTimeline` as a read-only snapshot. It must upload images through the existing private upload protocol, allow deterministic image ordering and cover selection, and show specific validation errors. Its submit payload is:

```ts
{
  version_no: selectedVersionNo,
  title: title.trim(),
  recap_text: recapText.trim(),
  cover_media_id: coverMediaId,
  media_ids: mediaIds,
}
```

After a 201 response, navigate to `/community/${post.id}` only if the backend allows author access to pending notes; otherwise navigate to a clearly labeled “我的田野笔记” route added as part of this task. Do not fake a public detail success for a pending note.

- [ ] **Step 4: Implement an author-status page if required by access rules**

Add `/community/mine` behind `requiresConsumer` and an API call to `GET /posts/me/field-notes`. It must show pending, published, rejected, and hidden statuses with moderation reason, and link only published entries to their public detail route. Use this page as the post-submit landing target if pending author detail is not exposed.

- [ ] **Step 5: Run frontend validation**

Run: `npm run test -- fieldNotes.test.ts; npm run typecheck; npm run build`

Expected: all commands PASS.

- [ ] **Step 6: Commit publishing workflow**

```bash
git add frontend-c/src/features/community/FieldNotePublishPage.vue frontend-c/src/features/community/FieldNotesMinePage.vue frontend-c/src/features/community/fieldNotesApi.ts frontend-c/src/features/community/fieldNotes.test.ts frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue frontend-c/src/features/itineraries/api.ts frontend-c/src/router/index.ts
```

## Task 7: Moderation Compatibility, Documentation, and Acceptance

**Files:**
- Modify: `backend/app/modules/admin/router.py` only if current admin post response omits needed field-note title/status/source fields.
- Modify: `frontend-b/src/features/admin/pages/OperationsPage.vue` or the actual existing post-moderation page only if existing controls cannot identify an itinerary post.
- Modify: `docs/API设计.md`
- Modify: `docs/本地验收使用手册.md`
- Modify: `docs/项目进度与完成度总结.md` only if it has a community completion statement that becomes inaccurate.
- Test: existing community/admin/worker tests plus browser acceptance.

**Interfaces:**
- Existing admin approval/rejection/hide endpoints operate unchanged on field-note posts.
- Existing `post.published` outbox event remains emitted with `content_type="itinerary"`; community knowledge review remains a separate optional moderator decision.

- [ ] **Step 1: Write a regression test for moderation and index compatibility**

```python
@pytest.mark.anyio
async def test_publishing_field_note_preserves_post_outbox_contract(session):
    await service.publish(field_note.id, admin.id, "reviewed", is_admin=True)
    event = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == field_note.id))
    assert event.event_type == "post.published"
    assert event.payload_json["content_type"] == "itinerary"
```

- [ ] **Step 2: Run the regression test and verify it fails only if behavior regressed**

Run: `pytest tests/community/test_services.py -k "field_note and publication" -v`

Expected: PASS after Tasks 1-3. Investigate any failure rather than changing moderation behavior casually.

- [ ] **Step 3: Make narrow admin presentation updates**

Ensure the administrative post list identifies `content_type="itinerary"` as “田野笔记”, shows title, author, status, moderation reason, and whether a route snapshot is attached. It must not expose private original itinerary data, copied itinerary IDs, media pre-signed URLs, or stored snapshot internals. Reuse the existing approval/rejection/hide endpoints and audit mechanism.

- [ ] **Step 4: Update API and local acceptance documentation**

Document the exact publish/copy routes, idempotency behavior, snapshot/public-private boundary, image constraints, published-only read/copy rule, moderation workflow, and no automatic promotion from field-note content to official RAG knowledge.

Add a local acceptance scenario:

```text
1. Create a two-day itinerary with ordered POIs and notes.
2. Publish it with a recap and JPEG/PNG/WebP cover through the workspace.
3. Approve it as an administrator.
4. Open the public field-note feed/detail in a logged-out browser.
5. Log in as another consumer, comment, react, favorite, then copy once.
6. Retry the same copy request with its original Idempotency-Key and verify the same itinerary returns.
7. Edit the copied itinerary; verify neither public snapshot nor source itinerary changes.
8. Check mobile and desktop screenshots for no clipped copy controls, gallery, route text, or comments.
```

- [ ] **Step 5: Run complete verification**

Run from `backend`:

```bash
pytest tests/community tests/itineraries tests/admin/test_community_knowledge_review_router.py tests/workers/test_community_knowledge_index.py -v
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Run from `frontend-c`:

```bash
npm run typecheck
npm run build
```

Start consumer development server with `npm run dev`, use a free port if `5173` is occupied, and perform the eight-step browser scenario at desktop and mobile viewport sizes. Record no tokens, pre-signed URLs, passwords, or raw private images in artifacts.

- [ ] **Step 6: Commit docs and acceptance changes**

```bash
git add backend/app/modules/admin frontend-b/src/features/admin docs/API设计.md docs/本地验收使用手册.md docs/项目进度与完成度总结.md backend/tests/community/test_services.py
```

## Plan Self-Review

### Spec coverage

- Existing `Post` extension, frozen version snapshots, image support, moderation, interaction reuse, copy counting, and source attribution: Tasks 1-3.
- Public discovery, independent detail page, responsive route presentation, copy CTA, and state handling: Task 5.
- Workspace-originated publication, version selection, preview, image ordering, and author status: Task 6.
- Field / Travel visual constraints, keyboard focus, reduced motion, docs, migration lifecycle, tests, and browser validation: Tasks 5 and 7.
- Community knowledge boundary and no exposure of private itinerary fields: Tasks 2, 3, and 7.

### Type consistency

- Backend creation uses `FieldNoteCreate`; consumer request type is `FieldNotePublishRequest` with the same serialized fields: `version_no`, `title`, `recap_text`, `cover_media_id`, `media_ids`.
- Copy uses `FieldNoteCopyResponse` containing `ItineraryResponse`, `source_post_id`, and `idempotent`; the consumer routes from `result.itinerary.id`.
- Public snapshots are produced by `_public_itinerary_snapshot` and consumed only by read/copy flows; copying materializes fresh rows through `_materialize_public_snapshot`.

### Scope check

This plan implements the approved field-note sample as one cohesive capability. A full consumer-wide visual redesign remains explicitly out of scope; its future design system should extend the verified field-note visual language rather than be bundled into this implementation.
