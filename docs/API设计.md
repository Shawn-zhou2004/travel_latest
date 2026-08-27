# AI Travel Platform API Contract

> Contract status: full-scope target contract; only `GET /` and `GET /api/v1/health` are currently implemented.
> Shared enums, permissions, events, and technical dependency map: `docs/contracts/`

## Global Contract

Every route below is an absolute path and includes the `/api/v1` prefix. Paths use plural kebab-case nouns; JSON fields use snake_case. Public IDs are UUID strings, timestamps are UTC RFC 3339, local itinerary dates are `YYYY-MM-DD`, money is a decimal string plus a three-character ISO currency, and list responses are `{ "items": [], "next_cursor": null }` using opaque cursor pagination.

Errors are `{ "code", "message", "request_id", "details" }`; every successful response exposes `request_id`. Protected routes require `Authorization: Bearer <access_token>`. C-end routes require a C-end audience token; B-end routes require a B-end audience token. Resource ownership, accepted collaboration role, and provider scope are checked under `docs/contracts/权限矩阵.md`.

Create-task, import, export, order, payment, refund, booking, membership, and package purchase writes require `Idempotency-Key`. Itinerary structure writes require `If-Match-Version`; collaborative itinerary writes also require `X-Operation-ID`. `201` creates, `202` accepts asynchronous work, `204` deletes/revokes, `409` reports version/idempotency/state conflicts, and `502`/`503`/`504` expose upstream failure or unavailability.

## Shared Schemas

| Name | Required fields |
|---|---|
| `Itinerary` | `id`, `owner_id`, `title`, `destination`, `start_date`, `end_date`, `visibility`, `version`, `status`, `days` |
| `ItineraryEvent` | `id`, `day_id`, `poi_id`, `name`, `latitude`, `longitude`, `display_order`, `source`, `source_updated_at`, `status` |
| `Job` | `id`, `status`, `progress`, `error_code`, `created_at`, `updated_at` |
| `TravelOrder` | `id`, `order_no`, `amount`, `currency`, `status`, `payment_status`, `fulfillment_status`, `failure_code`, `created_at` |
| `PaymentRecord` | `id`, `payment_no`, `provider`, `amount`, `currency`, `status`, `paid_at` |
| `ProviderResource` | `id`, `provider_id`, `status`, `created_at`, `updated_at` |
| `AdminAction` | `id`, `actor_id`, `action`, `target_type`, `target_id`, `created_at` |

`TravelOrder.status`, `payment_status`, and `fulfillment_status` are independent required response fields and use the canonical enums in `docs/contracts/说明.md`.

## Identity And Media

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `POST /api/v1/auth/sms-codes` | Anonymous | `{phone, captcha_token}` | `202 {request_id, expires_in}` |
| `POST /api/v1/auth/sessions` | Anonymous | `{phone, code, device_name}` | `201 {access_token, token_type, expires_in, user}`; refresh token is a secure HTTP-only cookie |
| `POST /api/v1/auth/sessions/refresh` | Refresh cookie | `{}` | `{access_token, token_type, expires_in, user}` |
| `DELETE /api/v1/auth/sessions/current` | User | `{}` | `204` |
| `GET /api/v1/auth/me` | User | None | `{id, nickname, roles, provider_memberships, entitlements}` |
| `PATCH /api/v1/users/me` | User | `{nickname?, avatar_asset_id?}` | `{id, nickname, avatar_asset_id, updated_at}` |
| `POST /api/v1/auth/wechat/authorization-requests` | Anonymous | `{redirect_uri}` | `201 {authorization_url, expires_in}` |
| `GET /api/v1/auth/wechat/callback` | Anonymous | Query `{code, state}` | Redirect or session response; unavailable returns `OAUTH_NOT_AVAILABLE` |
| `DELETE /api/v1/auth/wechat/identity` | User | `{}` | `204` |
| `POST /api/v1/media/upload-requests` | User | `{purpose, mime_type, size_bytes, sha256}` | `201 {asset_id, upload_url, headers, expires_at}` |
| `POST /api/v1/media/{asset_id}:complete` | Asset owner | `{etag, size_bytes}` | `{id, status, mime_type, size_bytes}` |
| `GET /api/v1/media/{asset_id}/download-url` | Authorized asset reader | None | `{url, expires_at}` |
| `POST /api/v1/media/{asset_id}:recognize` | Asset owner | `{target_itinerary_id?}` | `202 {import_job_id, status:"queued", progress:0, request_id}`; recognition does not insert itinerary events |

## Itineraries, Maps, And Jobs

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `GET /api/v1/itineraries` | User | Query `{cursor?, limit?, status?, city_code?}` | Paginated `Itinerary` summaries |
| `POST /api/v1/itineraries` | User | `{title, destination, start_date, end_date, visibility}` | `201 Itinerary` |
| `POST /api/v1/itineraries:manual-plan` | User | `{destination:{name, display_address, city_code}, start_date, end_date, title?}` | `201 Itinerary`; creates every requested date with no events and does not require AI, RAG, MCP, or Worker services |
| `GET /api/v1/itineraries/{itinerary_id}` | Owner, accepted collaborator, or valid link token | Query `{share_token?}` | `Itinerary` |
| `PATCH /api/v1/itineraries/{itinerary_id}` | Owner or accepted editor | `{title?, visibility?, preferences?}` | `Itinerary` with incremented `version` |
| `DELETE /api/v1/itineraries/{itinerary_id}` | Owner only | None | `204` |
| `POST /api/v1/itineraries/{itinerary_id}/archive` | Owner | `{}` | `Itinerary` |
| `POST /api/v1/itineraries/{itinerary_id}/days` | Owner or editor | `{day_date, title?}` | `201 {day, version}` |
| `PATCH /api/v1/itineraries/{itinerary_id}/days/{day_id}` | Owner or editor | `{title?, day_date?}` | `{day, version}` |
| `POST /api/v1/itineraries/{itinerary_id}:operations` | Owner or accepted editor | `{operation_type:"remove_day", payload:{day_id}}` plus `If-Match-Version` and `X-Operation-ID` headers | `OperationResponse` |
| `GET /api/v1/pois` | User | Query `{keyword, city_code?, category?, cursor?, limit?}` | Paginated `{id, name, category, district, latitude, longitude, source_updated_at}` |
| `GET /api/v1/pois/{poi_id}` | User | None | `{id, name, category, district, latitude, longitude, source, source_updated_at}` |
| `POST /api/v1/itineraries/{itinerary_id}/days/{day_id}/events` | Owner or editor | `{poi_id, insert_after_event_id?, stay_minutes?, planned_start_time?}` | `201 {event: ItineraryEvent, version}` |
| `PATCH /api/v1/itineraries/{itinerary_id}/days/{day_id}/events/{event_id}` | Owner or editor | `{poi_id?, stay_minutes?, planned_start_time?, planned_end_time?}` | `{event: ItineraryEvent, version}` |
| `DELETE /api/v1/itineraries/{itinerary_id}/days/{day_id}/events/{event_id}` | Owner or editor | None | `204` |
| `POST /api/v1/itineraries/{itinerary_id}/days/{day_id}/events:reorder` | Owner or editor | `{ordered_event_ids}` | `{version, route_job_id}` |
| `POST /api/v1/itineraries/{itinerary_id}/days/{day_id}/routes:recalculate` | Owner or editor | `{travel_mode?}` | `202 {route_job_id, status}` |
| `POST /api/v1/itineraries/{itinerary_id}/days/{day_id}/routes:optimize-preview` | Owner or editor | `{constraints?}` | `201 {preview_id, ordered_event_ids, saved_distance_meters, saved_duration_seconds, expires_at}` |
| `POST /api/v1/itineraries/{itinerary_id}/days/{day_id}/routes:apply-optimization` | Owner or editor | `{preview_id}` | `{itinerary_id, version, days}` |
| `POST /api/v1/itineraries/{itinerary_id}/days/{day_id}/adjustment-previews` | Owner or editor | `{instruction}` | `201 {preview_id, changes, expires_at}` |
| `POST /api/v1/itineraries/{itinerary_id}/days/{day_id}/adjustment-previews/{preview_id}:apply` | Owner or editor | `{}` | `{itinerary_id, version, days}` |
| `GET /api/v1/itineraries/{itinerary_id}/versions` | Owner or collaborator | Query `{cursor?, limit?}` | Paginated `{id, version_no, source, change_summary, created_at}` |
| `GET /api/v1/itineraries/{itinerary_id}/versions/{version_no}` | Owner or collaborator | None | `{id, version_no, snapshot, created_at}` |
| `POST /api/v1/itineraries/{itinerary_id}/versions/{version_no}/restore` | Owner or editor | `{}` | `{itinerary_id, version, restored_from_version_no}` |
| `POST /api/v1/itineraries/{itinerary_id}/field-notes` | Owner or accepted editor | `{version_no>=1, title, recap_text, cover_media_id, media_ids}` | `201 FieldNote`; freezes the selected version and starts at `pending_review` |
| `POST /api/v1/generation-jobs` | User | `{destination:{name, display_address, city_code}, start_date, end_date, preference_tags, prompt}` | `201 Job` with `generation_job_id`; destination must be selected from `GET /api/v1/destinations`, `preference_tags` has at most three approved values, and `prompt` may be empty |
| `GET /api/v1/generation-jobs/{job_id}` | Requester or admin | None | `Job` plus `itinerary_id?`, `version_id?` |
| `GET /api/v1/generation-jobs/{job_id}/events` | Requester or admin | `Last-Event-ID?` | SSE `progress` and `completed` events containing `{job_id, status, progress, trace_id, itinerary_id?, version_id?}` |
| `POST /api/v1/generation-jobs/{job_id}/retry` | Requester or admin | `{}` | `201 Job` |

### Itinerary Deletion

`DELETE /api/v1/itineraries/{itinerary_id}` permanently deletes an itinerary only when the authenticated caller is its owner. The request has no body and returns `204` without a response body. A missing itinerary returns `404 ITINERARY_NOT_FOUND`; a non-owner returns `403 FORBIDDEN`; and an itinerary referenced by a companion plan in `open`, `full`, or `closed` state returns `409 COMPANION_PLAN_ACTIVE`.

The deletion is one transaction. It removes itinerary days, events, route segments, route-calculation jobs, export tasks, operation history, itinerary versions, collaborators, share tokens, and itinerary-copy operation rows before deleting the itinerary. Field-note posts retain their frozen snapshots while their `itinerary_id` and `itinerary_version_id` are cleared. Companion-request and generation-job itinerary references are likewise cleared. A failed authorization or active-companion guard leaves every row unchanged.

Day deletion is implemented exclusively as the versioned itinerary operation below; `DELETE /api/v1/itineraries/{itinerary_id}/days/{day_id}` is not an implemented endpoint.

```http
POST /api/v1/itineraries/{itinerary_id}:operations
If-Match-Version: 3
X-Operation-ID: 55ac419f-5ef2-4582-82f5-2ad16ecc1b52
Content-Type: application/json

{"operation_type":"remove_day","payload":{"day_id":"<day UUID>"}}
```

An owner or accepted editor may submit `remove_day`. It removes the selected day's events, route segments, and route-calculation jobs, reorders the remaining days from `0`, increments the itinerary version, records the operation and version snapshot, and returns `APPLIED` with the new `current_version` and snapshot. Retrying the same `X-Operation-ID` returns the original applied result with `idempotent:true`; a stale `If-Match-Version` returns `VERSION_CONFLICT` with the current snapshot; an inaccessible itinerary returns `FORBIDDEN` or `NOT_FOUND`; and a day outside the itinerary returns `NOT_FOUND`. Removing the final day leaves the itinerary itself with zero days and keeps its existing `start_date` and `end_date`; otherwise its date range is recalculated from the remaining days.

### Consumer Destination And Smart Planning

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `GET /api/v1/destinations` | User | Query `{query}`; 1--80 non-blank characters after trimming | `{items:[{id, name, display_address, city_code, kind}]}` where `kind` is `city`, `district`, or `scenic_area` |

`GET /api/v1/destinations?query=长沙` returns normalized, backend-provided destination choices. A valid query with no match returns an empty `items` array. The selected object, rather than user-entered administrative-code text, is required by both planning actions.

### Reviewed POI Recommendations

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `GET /api/v1/admin/ai/poi-candidates` | Platform admin | Query `{status?, city_code?, limit?}` | Candidate POI page |
| `PATCH /api/v1/admin/ai/poi-candidates/{candidate_id}` | Platform admin | `{status, tags?, admin_weight?, reason?}` | Candidate POI |

Only POIs from user-confirmed, AMap-verified AI previews enter the candidate queue. They start as `pending_review`; they are not official knowledge and are not recommendable. An administrator may approve a candidate with at least one supported travel tag and an internal weight from `0` through `100`. Approval creates a separate `pending_review` official POI knowledge source, which still requires the existing official knowledge review before indexing.

Planning ranks approved candidates within the requested city by administrator weight, confirmed itinerary count, and discovery count. It then re-verifies each POI with AMap and retains the existing city/type/deduplication safeguards. Third-party ratings are not collected or represented. Live web and AMap discovery remain a fallback when approved candidates and reviewed knowledge cannot provide two unique places per day.

### Official Travel Assistant

`POST /api/v1/ai/conversations/{conversation_id}:ask` accepts `{text, client_message_id}`. It queries the unified official travel knowledge domain across all reviewed public sources; consumers do not provide an administrative code. Users should name a destination naturally in their question when it matters. Administrative city codes remain internal constraints for selected destinations, POI verification, and itinerary generation.

Administrators add detailed official sources through `POST /api/v1/admin/ai/knowledge-sources` with `{source_type:"poi", title, body_text, city_code:"460200", poi_id, language}`. The source remains `pending_review` until a platform administrator approves and indexes it. For a detailed Sanya answer, each attraction should have its own source with the attraction name, overview, features, suggested visit content, audience, duration, notices, and clearly bounded real-time information. A POI-only name is insufficient evidence for a detailed assistant answer.

`POST /api/v1/ai/conversations/{conversation_id}:ask-stream` accepts the same request and returns authenticated SSE. It first persists the user message and a reconnectable assistant run, then emits `progress`, `delta`, and terminal `completed` or `failed` events. `GET /api/v1/ai/assistant-runs/{run_id}/events` replays a completed message or current terminal/progress state for the owning consumer. The assistant searches reviewed official knowledge first; only `no_results`, `clarification_required`, or an irrelevant global-RAG match invokes configured WebSearch MCP. Live search receives the original user question, ranks and deduplicates HTTPS candidates by query coverage, concrete attraction cues, and source quality, then fetches up to five top results. Robots-denied responses, unreadable pages, and duplicate text are discarded; readable text is bounded and chunked before being provided to the model. A second precise query is used only when the first evidence set has no concrete attraction content. Neither search nor fetched pages are indexed or written to long-term knowledge automatically.

```json
{
  "items": [
    {
      "id": "430100",
      "name": "长沙市",
      "display_address": "中国 · 湖南省 · 长沙市",
      "city_code": "430100",
      "kind": "city"
    }
  ]
}
```

`POST /api/v1/itineraries:manual-plan` creates a synchronous, editable date skeleton. For example:

```json
{
  "destination": {
    "name": "长沙市",
    "display_address": "中国 · 湖南省 · 长沙市",
    "city_code": "430100"
  },
  "start_date": "2026-08-10",
  "end_date": "2026-08-12",
  "title": "长沙三日游"
}
```

The `201 Itinerary` response contains the three consecutive dates and an empty `events` array for each date. This endpoint does not enqueue a generation job or call AI-related dependencies.

`POST /api/v1/generation-jobs` accepts the same selected destination plus structured preferences. The public request does not accept a separately typed `city_code`; the backend derives workflow city scope from `destination.city_code`.

```json
{
  "destination": {
    "name": "长沙市",
    "display_address": "中国 · 湖南省 · 长沙市",
    "city_code": "430100"
  },
  "start_date": "2026-08-10",
  "end_date": "2026-08-12",
  "preference_tags": ["吃吃喝喝", "citywalk", "历史古建"],
  "prompt": "有老人同行"
}
```

The allowed `preference_tags` values are `经典必玩`, `吃吃喝喝`, `小众探索`, `拍照出片`, `逛街购物`, `citywalk`, `自然风光`, `文艺展览`, and `历史古建`; duplicate values are invalid. A generation request snapshot preserves the selected destination, derived city scope, preference tags, prompt, and dates.

Generation progress may report `resolving_destination`, `retrieving_reviewed_sources`, `searching_live_sources`, `verifying_pois`, `planning`, and `validating`. These status values contain no source query, raw excerpt, raw page body, or URL query parameters. A terminal successful job with `outcome:"no_result"` means fewer than two verified places could be assembled for at least one requested day; it creates no itinerary write. Dependency failures remain unavailable outcomes rather than no-result outcomes.

Smart planning searches reviewed knowledge first. Only when reviewed, verified candidates cannot cover two places per requested day may it use one bounded, task-local live MCP search fallback. A live citation returned in a preview has `source_type:"live_web"`; reviewed citations have `source_type:"reviewed_knowledge"`. Live MCP title, excerpt, host, and HTTPS source URL metadata are evidence for that task and preview only: raw pages and URLs are not fetched or indexed, and no live result is inserted into Milvus, Elasticsearch, or long-term knowledge tables without the separate administration review workflow. Every planned stop must retain a citation and pass AMap verification for a non-empty POI ID, target-city membership, and coordinates.

## Sharing, Import, Export, Guide, Checklist, And Budget

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `POST /api/v1/itineraries/{itinerary_id}/share-tokens` | Owner | `{expires_at?}` | `201 {id, share_url, token, expires_at}`; token appears once |
| `DELETE /api/v1/itineraries/{itinerary_id}/share-tokens/{token_id}` | Owner | None | `204` |
| `POST /api/v1/itineraries/{itinerary_id}/collaborators` | Owner | `{user_id, role}` | `201 {id, user_id, role, invite_status}` |
| `PATCH /api/v1/itineraries/{itinerary_id}/collaborators/{collaborator_id}` | Owner | `{role?, invite_status?}` | `{id, role, invite_status}` |
| `POST /api/v1/itineraries/{itinerary_id}/collaborators/{collaborator_id}:accept` | Invited user | `{}` | `{id, invite_status}` |
| `POST /api/v1/public/itineraries/{itinerary_id}:copy` | User | `{source_version_no?}` | `201 Itinerary` |
| `POST /api/v1/import-jobs` | User | `{source_type, source_url?, source_asset_id?, target_itinerary_id?}` | `201 Job` with `import_job_id` |
| `GET /api/v1/import-jobs/{job_id}` | Requester or admin | None | `{id, status, progress, error_code?, target_itinerary_id?, candidates:[{candidate_id, recognized_name, confidence, proposed_day_date?, proposed_display_order?, amap_candidates:[{poi_id, name, category, district, latitude, longitude}]}], created_at, updated_at}` |
| `POST /api/v1/import-jobs/{job_id}:confirm` | Requester | `{target_itinerary_id, candidates:[{candidate_id, poi_id, day_date, display_order}]}` where every `poi_id` is selected from that candidate's `amap_candidates` | `{import_job_id, itinerary_id, version, status:"succeeded", inserted_event_ids}`; unconfirmed or unmatched candidates return `VALIDATION_POI_REQUIRED` and create no itinerary event |
| `POST /api/v1/export-tasks` | User | `{itinerary_id, version_id? or version_no?, format:"docx"}` | `201 ExportTask` |
| `GET /api/v1/export-tasks/{task_id}` | Requester | None | `ExportTask` with status, progress, and output availability |
| `GET /api/v1/export-tasks/{task_id}/download-url` | Requester | None | Short-lived DOCX attachment URL after successful export |
| `GET /api/v1/itineraries/{itinerary_id}/checklists` | Owner or collaborator | None | `{items:[{id, category, content, checked, source}]}` |
| `POST /api/v1/itineraries/{itinerary_id}/checklists` | Owner or editor | `{category, content}` | `201 {id, category, content, checked}` |
| `PATCH /api/v1/checklists/{item_id}` | Owner or editor | `{content?, checked?}` | `{id, category, content, checked}` |
| `GET /api/v1/itineraries/{itinerary_id}/budgets` | Owner or collaborator | None | `{items, total_amount, currency}` |
| `POST /api/v1/itineraries/{itinerary_id}/budgets` | Owner or editor | `{category, amount, currency, description?}` | `201 {id, category, amount, currency}` |
| `PATCH /api/v1/budgets/{item_id}` | Owner or editor | `{category?, amount?, description?}` | `{id, category, amount, currency}` |
| `POST /api/v1/guide/sessions` | User | `{itinerary_id, language, auto_play}` | `201 {id, itinerary_id, status, started_at}` |
| `GET /api/v1/guide/sessions/{session_id}` | Session owner or admin | None | `{id, itinerary_id, language, auto_play, status}` |
| `PATCH /api/v1/guide/sessions/{session_id}` | Session owner | `{auto_play?, status?}` | `{id, status, auto_play}` |
| `GET /api/v1/guide/sessions/{session_id}/nearby` | Session owner | Query `{latitude, longitude}` | `{poi_id?, distance_meters?, narration_id?}` |
| `POST /api/v1/narration-jobs` | User | `{itinerary_id, poi_id, language}` | `202 Job` |
| `GET /api/v1/poi-narrations/{narration_id}` | Authorized itinerary reader | None | `{id, poi_id, script, sources, audio_url?, status}` |

## Community, Companion, Chat, And Notifications

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `GET /api/v1/posts` | Anonymous | Query `{content_type=itinerary, city_code?, q?, sort=latest\|recommended, cursor?, limit=1..50}` | `FieldNotePage`; only `published` itinerary posts. Without `content_type`, returns the legacy published-post page. |
| `POST /api/v1/posts` | User | `{content_type:"note"?, title, body_text, city_code?}` | `201 PostResponse`; generic creation cannot create itinerary field notes. |
| `GET /api/v1/posts/me/field-notes` | User | None | Author's `FieldNote[]`, including `pending_review`, `rejected`, `hidden`, `published`, and `moderation_reason`. |
| `GET /api/v1/posts/{post_id}` | Anonymous | None | A published `FieldNote` for itinerary posts, or a legacy `PostResponse`; unpublished posts return `404`. |
| `POST /api/v1/posts/{post_id}:copy-itinerary` | User | Empty body and required `Idempotency-Key` header (1--128 chars) | `201 {itinerary, source_post_id, idempotent}`; retry with the same actor, source post, and key returns the original itinerary with `idempotent:true` and does not increment `copy_count`. Only published field notes are copyable. |
| `POST /api/v1/posts/{post_id}:submit` | Author | None | `PostResponse`; legacy draft only. |
| `POST /api/v1/posts/{post_id}:publish` | Author | None | `PostResponse`; legacy pending post only. |
| `POST /api/v1/posts/{post_id}/reactions` | User | `{type:"like"}` | `201 {post_id, type, created_at}` |
| `DELETE /api/v1/posts/{post_id}/reactions/like` | User | None | `204` |
| `POST /api/v1/posts/{post_id}/favorites` | User | `{}` | `201 {post_id, created_at}` |
| `DELETE /api/v1/posts/{post_id}/favorites` | User | None | `204` |
| `GET /api/v1/posts/{post_id}/comments` | Anonymous if post published | Query `{cursor?, limit?}` | Paginated `{id, author, parent_id?, body, created_at}` |
| `POST /api/v1/posts/{post_id}/comments` | User | `{body, parent_id?}` | `201 {id, body, parent_id?, created_at}` |
| `POST /api/v1/reports` | User | `{target_type, target_id, reason, details?}` | `201 {id, status:"pending"}` |
| `POST /api/v1/users/{user_id}/follows` | User | `{}` | `201 {user_id, created_at}` |
| `DELETE /api/v1/users/{user_id}/follows` | User | None | `204` |
| `GET /api/v1/companion-requests` | Anonymous | Query `{city_code?, start_date?, end_date?, trip_kind?, travel_pace?, tags?, has_slots?, cursor?, limit=1..50}` | Cursor-paginated public `CompanionPlanSummary[]`; only `review_status:"approved"` and `status:"open"` plans are listed. |
| `GET /api/v1/companion-requests/{request_id}` | Anonymous or consumer | None | Public `CompanionPlanDetail`; owner and accepted members additionally receive `itinerary_id`, `conversation_id`, `members`, and `protected_itinerary`. |
| `GET /api/v1/companion-requests/mine` | Consumer | None | Owned plans plus plans with the caller's `pending` or `accepted` application. |
| `POST /api/v1/itineraries/{itinerary_id}/companion-requests` | Itinerary owner or accepted editor | `{party_size:2..12, budget_min?, budget_max?, currency?, travel_pace:"slow"\|"balanced"\|"packed", interest_tags, intro_text}` | `201 CompanionPlanResponse`; requires a current itinerary version with at least one stop and creates an `open`/`pending_review` trip plan. |
| `POST /api/v1/companion-requests:activity` | Consumer | Plan metadata plus `{title, city_code, activity_date, starts_at, ends_at, poi_id}` | `201 CompanionPlanResponse`; verifies the POI and creates the one-day itinerary and `open`/`pending_review` activity plan atomically. |
| `PATCH /api/v1/companion-requests/{request_id}` | Plan owner | `{title?, city_code?, description?}` | `CompanionRequestResponse`; only an `open` plan may be edited. |
| `POST /api/v1/companion-requests/{request_id}:close` | Plan owner | None | `CompanionRequestResponse`; stops recruitment. |
| `POST /api/v1/companion-requests/{request_id}:reopen` | Plan owner | None | `CompanionRequestResponse`; only an approved, non-full `closed` plan can reopen. |
| `POST /api/v1/companion-requests/{request_id}:cancel` | Plan owner | None | `CompanionRequestResponse`; only an `open` plan can cancel. |
| `POST /api/v1/companion-requests/{request_id}:complete` | Plan owner | None | `CompanionRequestResponse`; ends the plan and revokes non-owner itinerary editing. |
| `POST /api/v1/companion-requests/{request_id}:leave` | Accepted member | None | `CompanionRequestResponse`; revokes that member's future itinerary and group access. |
| `DELETE /api/v1/companion-requests/{request_id}/members/{user_id}` | Plan owner | None | `CompanionRequestResponse`; removes an accepted non-owner member. |
| `GET /api/v1/companion-requests/{request_id}/applications` | Plan owner | None | `CompanionApplication[]`, including required application explanation. |
| `POST /api/v1/companion-requests/{request_id}/applications` | Consumer | `{message}`; 1--1,000 non-whitespace characters | `201 {id, status:"pending"}`; plan must be approved, open, and have capacity. |
| `GET /api/v1/companion-applications/mine` | Consumer | None | Caller's applications. |
| `POST /api/v1/companion-applications/{application_id}:accept` | Plan owner | First acceptance: `{group_name, group_avatar_asset_id}`; later acceptance: body omitted or both fields omitted | `{application, conversation_id, group_name, group_avatar_asset_id, plan_status, accepted_count}`; the first acceptance requires an owned completed JPEG/PNG/WebP avatar and creates the group atomically, while later acceptance reuses the same group without changing its profile. |
| `POST /api/v1/companion-applications/{application_id}:reject` | Plan owner | None | `{id, status:"rejected", conversation_id:null}` |
| `POST /api/v1/companion-applications/{application_id}:withdraw` | Applicant | None | `CompanionApplicationResponse`; only a pending application can be withdrawn. |
| `GET /api/v1/itineraries/{itinerary_id}/companion-workspace` | Current itinerary collaborator | None | Current role-safe `{id, status, party_size, accepted_count, role, conversation_id?}` or `null`. |
| `GET /api/v1/conversations` | Active conversation member | Query `{cursor?, limit?}` | Paginated `{id, conversation_type, title, avatar_asset_id, unread_count, last_message}` |
| `GET /api/v1/conversations/{conversation_id}/messages` | Conversation member | Query `{cursor?, limit?}` | Paginated `{id, sender_id, message_type, body_text?, payload?, created_at}` |
| `POST /api/v1/conversations/{conversation_id}/messages` | Conversation member | `{client_message_id, message_type, body_text?, asset_id?, payload?}` | `201 {id, client_message_id, created_at}` |
| `POST /api/v1/users/{user_id}/blocks` | User | `{}` | `201 {user_id, created_at}` |
| `DELETE /api/v1/users/{user_id}/blocks` | User | None | `204` |
| `GET /api/v1/notifications` | User | Query `{cursor?, limit?, unread_only?}` | Paginated `{id, notification_type, payload, read_at}` |
| `GET /api/v1/notifications/summary` | User | None | `{groups:[{conversation_id,title,avatar_asset_id,unread_count,last_message}],total_unread}`; contains only active companion groups with unread messages and never exposes application-accepted event rows. |
| `POST /api/v1/notifications:mark-read` | User | `{notification_ids?}` | `{updated_count}` |
| `GET /api/v1/media/{asset_id}/download-url` | Asset owner, or active member when the asset is that conversation's avatar | None | Short-lived private object URL. Former members and non-members receive the same `404 MEDIA_ASSET_NOT_FOUND` as an unknown asset. |

| `GET /api/v1/admin/companion-requests` | `platform_admin` | Query `{status?, limit=1..100}` | Moderation queue items contain only plan title, city code, type, itinerary presence, dates, capacity, accepted count, pace, tags, public intro, business status, review status/reason, and timestamps. |
| `PATCH /api/v1/admin/companion-requests/{request_id}` | `platform_admin` | `{status:"approved"\|"rejected", review_reason}` | Updates only a `pending_review` plan, records the audit action, and cancels a rejected plan. |

`FieldNote` is `{id, author_id, title, body_text:"", city_code?, status, published_at?, recap_text, itinerary_snapshot, cover_media_id?, media_ids, day_count, stop_count, copy_count}`. Publishing requires at least one owned, completed image; supported MIME types are exactly `image/jpeg`, `image/png`, and `image/webp`, with one to nine ordered `media_ids` and a cover ID included in that list. The service obtains the source itself and projects only title, dates, ordered day/event route data, POI snapshots, times, display order, and notes from the selected version. It excludes budgets, checklists, collaborators, share tokens, operation history, route jobs/segments, persisted day/event IDs, payment data, and unselected media. Later source-itinerary changes cannot change the stored field-note snapshot. Copies create fresh owner-only days and events and never mutate the source itinerary, source post, or frozen snapshot.

Administrative content approval, rejection, and hide use the existing post state machine. Publishing any field note writes the normal `post.published` outbox envelope with `content_type:"itinerary"`. A city-scoped published post receives a separate, optional `CommunityKnowledgeReview`; field-note publication never automatically promotes the snapshot or its source itinerary into community RAG. Only an administrator's separate community-knowledge approval emits `ai.community_knowledge_index_requested`.

`CompanionPlanSummary` exposes only title, city/date/type, capacity, budget, pace, tags, public intro, route count, cover candidate, business status, and the authenticated viewer's application state. Public and pending applicants never receive member IDs, contacts, group conversation IDs, protected itinerary snapshots, exact meeting details, or private itinerary notes. The business states are `open`, `full`, `closed`, `cancelled`, and `completed`; review remains the independent `pending_review`/`approved`/`rejected` moderation state. `party_size` includes the owner and `accepted_count` begins at one. Only approved open plans are discoverable or accept applications.

Before creation, application, acceptance, or adding a member relation, the service checks blocks in both directions without disclosing which user created the block. Acceptance locks the plan and atomically grants the applicant itinerary `editor` access, creates or reuses one `companion_group`, activates chat membership, stores the conversation ID on the accepted application, and updates capacity. The first acceptance changes nothing when either group profile field is missing or invalid; each later acceptance returns the existing conversation ID and profile and cannot create a second group. An active member may resolve the group's exact avatar asset through the private media endpoint, but membership grants no access to any other asset. Leaving or removal preserves historic itinerary changes but revokes future editor, chat, and group-avatar access; a full plan reopens when a member leaves. Completion revokes all non-owner collaborators, preserves active group membership for readable history, and the chat service rejects new companion-group messages with `COMPANION_PLAN_COMPLETED`.

Companion lifecycle facts are persisted as Outbox events and consumed by the notification worker; the community module does not write notification rows. Companion plans, applications, membership, protected itinerary content, conversations, messages, contact data, and block relationships are excluded from public and RAG domains. The admin moderation queue is likewise a safe metadata projection and never returns itinerary snapshots, conversations, messages, members, applications, contacts, or block facts.

## Travel Commerce

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `POST /api/v1/travel-search-jobs` | User | `{search_type, origin, destination, depart_date, return_date?, passenger_count, preferences?}` | `201 Job` |
| `GET /api/v1/travel-search-jobs/{job_id}` | Requester or admin | None | `Job` plus `{offer_count, expires_at}` |
| `GET /api/v1/travel-search-jobs/{job_id}/offers` | Requester or admin | Query `{cursor?, limit?}` | Paginated `{id, provider_code, offer_type, price_amount, currency, availability_status, valid_until}` |
| `POST /api/v1/travel-orders` | User | `{offer_id}` | `201 TravelOrder` |
| `GET /api/v1/travel-orders` | User or admin | Query `{cursor?, limit?, status?}` | Paginated `TravelOrder` |
| `GET /api/v1/travel-orders/{order_id}` | Owner or admin | None | `TravelOrder` plus `{offer_snapshot, payments, refunds}` |
| `POST /api/v1/travel-orders/{order_id}/payments` | Owner | `{provider:"alipay_sandbox"}` | `201 PaymentRecord` plus `{payment_payload}` |
| `POST /api/v1/travel-orders/{order_id}:query-payment` | Owner or admin | `{}` | `TravelOrder` |
| `POST /api/v1/travel-orders/{order_id}/refunds` | Owner or authorized provider/admin | `{amount, currency, reason}` | `201 {id, status, amount, currency}` |
| `POST /api/v1/payments/alipay/callback` | Alipay callback only | Provider callback fields | `{result:"success"}` after signature, amount, and merchant-order verification |

## Providers, Experiences, Packages, Memberships, And Entitlements

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `POST /api/v1/provider-applications` | User | `{provider_type, legal_name, contact, qualification_asset_ids, claimed_poi_ids?}` | `201 ProviderResource` with `status:"pending_review"` |
| `GET /api/v1/provider-applications/{application_id}` | Applicant or admin | None | `{id, provider_type, status, review_reason?, provider_id?}` |
| `GET /api/v1/provider-profile` | Provider staff | None | `{provider_id, profile, verification_status}` |
| `PATCH /api/v1/provider-profile` | Provider staff | `{name?, contact?, description?, qualification_asset_ids?}` | `{provider_id, updated_at}` |
| `GET /api/v1/provider/attractions` | Provider staff | Query `{cursor?, limit?, status?}` | Paginated `ProviderResource` |
| `POST /api/v1/provider/attractions` | Provider staff | `{poi_id, name, ticket_mode, official_url?, description?}` | `201 ProviderResource` |
| `GET /api/v1/provider/attractions/{attraction_id}` | Scoped provider staff | None | `ProviderResource` |
| `PATCH /api/v1/provider/attractions/{attraction_id}` | Scoped provider staff | `{ticket_mode?, official_url?, description?, status?}` | `ProviderResource` |
| `GET /api/v1/provider/attractions/{attraction_id}/routes` | Scoped provider staff | Query `{cursor?, limit?}` | Paginated `{id, attraction_id, title, nodes, status}` |
| `POST /api/v1/provider/attractions/{attraction_id}/routes` | Scoped provider staff | `{title, nodes, duration_minutes?}` | `201 {id, attraction_id, status}` |
| `PATCH /api/v1/provider/attraction-routes/{route_id}` | Scoped provider staff | `{title?, nodes?, status?}` | `{id, status, updated_at}` |
| `GET /api/v1/provider/promotions` | Provider staff | Query `{cursor?, limit?, status?}` | Paginated `ProviderResource` |
| `POST /api/v1/provider/promotions` | Provider staff | `{attraction_id?, title, budget_amount, currency, starts_at, ends_at, asset_ids}` | `201 ProviderResource` |
| `PATCH /api/v1/provider/promotions/{promotion_id}` | Scoped provider staff | `{title?, budget_amount?, starts_at?, ends_at?, status?}` | `ProviderResource` |
| `GET /api/v1/provider/experiences` | Provider staff | Query `{cursor?, limit?, status?}` | Paginated `ProviderResource` |
| `POST /api/v1/provider/experiences` | Provider staff | `{title, description, price_amount, currency, meeting_point, cancellation_policy, asset_ids}` | `201 ProviderResource` |
| `GET /api/v1/provider/experiences/{experience_id}` | Scoped provider staff | None | `ProviderResource` |
| `PATCH /api/v1/provider/experiences/{experience_id}` | Scoped provider staff | `{title?, description?, price_amount?, status?}` | `ProviderResource` |
| `GET /api/v1/provider/experiences/{experience_id}/sessions` | Scoped provider staff | Query `{cursor?, limit?}` | Paginated `{id, status, remaining_capacity}` |
| `POST /api/v1/provider/experiences/{experience_id}/sessions` | Scoped provider staff | `{starts_at, capacity, price_amount?, currency?}` | `201 {id, status, remaining_capacity}` |
| `PATCH /api/v1/provider/experience-sessions/{session_id}` | Scoped provider staff | `{starts_at?, capacity?, status?}` | `{id, status, remaining_capacity}` |
| `POST /api/v1/experience-bookings` | User | `{experience_session_id, traveler_count}` | `201 {id, status, travel_order_id}` |
| `GET /api/v1/experience-bookings/{booking_id}` | Booking owner, scoped provider, or admin | None | `{id, status, verification_code, travel_order_id, evaluation?}` |
| `GET /api/v1/provider/experience-bookings` | Scoped provider staff | Query `{provider_id, status?}` | `{items:[{id, experience_title, starts_at, traveler_count, status, verified_at}]}`; excludes traveler identity, payment facts, and verification codes |
| `POST /api/v1/provider/experience-bookings/{booking_id}:verify` | Scoped provider staff | `{verification_code}` | `{id, status:"verified", verified_at}` |
| `POST /api/v1/experience-bookings/{booking_id}/evaluations` | Completed booking owner | `{rating, body}` | `201 {id, rating, body, status}` |
| `POST /api/v1/provider/experience-bookings/{booking_id}/support-messages` | Booking owner or scoped provider | `{body, asset_ids?}` | `201 {id, sender_id, body, created_at}` |
| `GET /api/v1/itinerary-packages` | Anonymous for published packages | Query `{cursor?, limit?, city_code?, theme?}` | Paginated `{id, title, price_amount, currency, version, status}` |
| `GET /api/v1/attractions` | Anonymous for published attractions | Query `{cursor?, limit?, city_code?, category?}` | Paginated `{id, poi_id, name, ticket_mode, official_url?, status}` |
| `GET /api/v1/attractions/{attraction_id}` | Anonymous if published | None | `{id, poi_id, name, official_routes, official_url?, announcements, status}` |
| `GET /api/v1/experiences` | Anonymous for published experiences | Query `{cursor?, limit?, city_code?, provider_id?}` | Paginated `{id, title, price_amount, currency, provider, status}` |
| `GET /api/v1/experiences/{experience_id}` | Anonymous if published | None | `{id, title, description, sessions, cancellation_policy, provider, status}` |
| `POST /api/v1/itinerary-packages` | Platform admin | `{itinerary_version_id, title, city_code, theme, price_amount, currency, asset_id}` | `201 ProviderResource` |
| `GET /api/v1/itinerary-packages/{package_id}` | Anonymous if published | None | `{id, title, price_amount, currency, version, status}` |
| `PATCH /api/v1/itinerary-packages/{package_id}` | Platform admin | `{title?, price_amount?, status?, asset_id?}` | `{id, title, price_amount, currency, version, status}` |
| `POST /api/v1/itinerary-packages/{package_id}:purchase` | User | `{}` | `201 TravelOrder` or package-order read model with the state triplet |
| `GET /api/v1/membership-plans` | Anonymous for published plans | Query `{cursor?, limit?}` | Paginated purchasable-plan facts including `price_amount`, `currency`, `duration_days`, `generation_quota`, `assistant_quota`, and `purchasable` |
| `POST /api/v1/membership-purchases` | Consumer | `{membership_plan_id}` plus `Idempotency-Key` | `201` immutable purchase snapshot with `pending_payment/pending/pending` facts |
| `POST /api/v1/membership-purchases/{purchase_id}/qr-payments` | Purchase owner | None | `201 {attempt_id, payment_no, qr_code, expires_at, status, payment_status, authorization_status}`; QR code is local-rendering input and expires after 10 minutes |
| `GET /api/v1/membership-purchases/{purchase_id}/qr-payments/current` | Purchase owner | None | Current QR-attempt facts; returns the code only while its `pending`/`paying` attempt remains valid and marks overdue attempts `expired` |
| `POST /api/v1/membership-purchases/{purchase_id}/qr-payments:refresh` | Purchase owner | None | Replacement QR-attempt facts; only allowed after current attempt is `expired` or `closed`, reuses the purchase and creates a new payment number |
| `POST /api/v1/membership-purchases/{purchase_id}:query-payment` | Purchase owner | None | Server-confirmed redacted QR/payment facts; never returns `qr_code`, raw Alipay response, signature, or callback payload |
| `GET /api/v1/membership-purchases/mine` | Consumer | None | Purchase snapshots without QR code, payment numbers, signatures, callbacks, or provider transaction IDs |
| `POST /api/v1/membership-payments/alipay/callback` | Alipay | URL-encoded signed callback | Plain text `success` or `failure`; verifies signature, App ID, payment number, amount, transaction binding, and successful trade status before settlement |
| `GET /api/v1/users/me/ai-entitlements` | User | None | Current free and active membership generation/conversation quota facts and upgrade availability |
| `GET /api/v1/users/me/entitlements` | User | None | `{items:[{id, entitlement_type, source_order_id, valid_from, valid_until, status}]}` |

## Administration And Integration Operations

All routes in this section require `platform_admin`, except provider-scoped reads which additionally permit matching provider staff. Every mutation creates an `AdminAction` and follows the target aggregate state machine.

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `GET /api/v1/admin/users/{user_id}` | Platform admin | None | `{id, phone_masked, nickname, status, roles, provider_memberships, created_at, updated_at}` |
| `PATCH /api/v1/admin/users/{user_id}` | Platform admin | `{status?, roles?}` | `{id, phone_masked, nickname, status, roles, updated_at}` |
| `GET /api/v1/admin/posts` | Platform admin | Query `{status?, limit=1..100}` | `{items:[{id, author_id, content_type, title, body, status, moderation_reason?, has_route_snapshot, created_at, updated_at}], next_cursor:null}`; `has_route_snapshot` is the only route-snapshot indicator and the response excludes snapshot contents, source/copy IDs, and media URLs. |
| `PATCH /api/v1/admin/posts/{post_id}` | Platform admin | `{status:"published"\|"rejected"\|"hidden", moderation_reason}` | `{id, status, moderation_reason?}`; a non-blank moderation reason is required. |
| `GET /api/v1/admin/reports/{report_id}` | Platform admin | None | `{id, reporter_id, target_type, target_id, reason, details?, status, resolution?, resolved_by?, resolved_at?, created_at}` |
| `PATCH /api/v1/admin/reports/{report_id}` | Platform admin | `{status, resolution?}` | `{id, status, resolution?, resolved_by?, resolved_at?}` |
| `GET /api/v1/admin/providers/{provider_id}` | Platform admin | None | `{id, provider_type, legal_name, contact_masked, verification_status, review_reason?, member_count, created_at, updated_at}` |
| `PATCH /api/v1/admin/providers/{provider_id}` | Platform admin | `{status, review_reason?}` | `{id, verification_status, review_reason?, updated_at}` |
| `GET /api/v1/admin/attractions/{attraction_id}` | Platform admin | None | `{id, provider_id, poi_id, name, ticket_mode, official_url?, status, review_reason?, updated_at}` |
| `PATCH /api/v1/admin/attractions/{attraction_id}` | Platform admin | `{status?, review_reason?, official_url?}` | `{id, status, review_reason?, official_url?, updated_at}` |
| `GET /api/v1/admin/experiences/{experience_id}` | Platform admin | None | `{id, provider_id, title, price_amount, currency, status, review_reason?, session_count, updated_at}` |
| `PATCH /api/v1/admin/experiences/{experience_id}` | Platform admin | `{status?, review_reason?}` | `{id, status, review_reason?, updated_at}` |
| `GET /api/v1/admin/experience-bookings` | Platform admin | Query `{cursor?, limit?, status?, provider_id?}` | `{items:[{id, provider_id, experience_session_id, user_id, traveler_count, status, verification_code?, travel_order_id, created_at, updated_at}], next_cursor}` |
| `GET /api/v1/provider/travel-orders` | Scoped provider staff | Query `{cursor?, limit?, status?}` | Paginated `TravelOrder` limited to the provider scope |
| `GET /api/v1/provider/commission-ledger` | Scoped provider staff | Query `{cursor?, limit?, starts_at?, ends_at?}` | `{items:[{id, provider_id, travel_order_id, booking_id?, gross_amount, commission_rate, commission_amount, currency, status, recorded_at}], next_cursor}`; simulated accounting only, never settlement or withdrawal |
| `GET /api/v1/admin/commission-ledger` | Platform admin | Query `{cursor?, limit?, provider_id?, starts_at?, ends_at?}` | `{items:[{id, provider_id, travel_order_id, booking_id?, gross_amount, commission_rate, commission_amount, currency, status, recorded_at}], next_cursor}`; read-only simulated accounting, never settlement or withdrawal |
| `GET /api/v1/admin/narrations/{narration_id}` | Platform admin | None | `{id, poi_id, language, script, source_count, audio_asset_id?, status, review_reason?, created_at, updated_at}` |
| `PATCH /api/v1/admin/narrations/{narration_id}` | Platform admin | `{status, review_reason?}` | `{id, status, review_reason?, updated_at}` |
| `GET /api/v1/admin/generation-jobs` | Platform admin | Query `{cursor?, limit?, status?}` | Paginated `Job` |
| `GET /api/v1/admin/import-jobs` | Platform admin | Query `{cursor?, limit?, status?}` | Paginated `Job` |
| `GET /api/v1/admin/export-tasks` | Platform admin | Query `{cursor?, limit?, status?}` | Paginated `Job` |
| `GET /api/v1/admin/travel-orders` | Platform admin | Query `{cursor?, limit?, status?}` | Paginated `TravelOrder` |
| `GET /api/v1/admin/payments` | Platform admin | Query `{cursor?, limit?, status?}` | Paginated `PaymentRecord` |
| `GET /api/v1/admin/outbox-events` | Platform admin | Query `{cursor?, limit?, status?, event_type?}` | `{items:[{event_id, event_type, aggregate_type, aggregate_id, occurred_at, trace_id, payload, status, attempt_count, next_attempt_at?, published_at?, last_error?}], next_cursor}` |
| `GET /api/v1/admin/dead-letters` | Platform admin | Query `{cursor?, limit?}` | `{items:[{id, event_id, event_type, aggregate_type, aggregate_id, payload, failure_reason, failed_at, replay_count}], next_cursor}` |
| `POST /api/v1/admin/dead-letters/{event_id}:replay` | Platform admin | `{}` | `202 {event_id, replay_id, status}` |
| `GET /api/v1/admin/search-indexes` | Platform admin | None | `{items:[{name, status, document_count, last_indexed_at}]}` |
| `POST /api/v1/admin/search-indexes:rebuild` | Platform admin | `{index_name}` | `202 Job` |
| `GET /api/v1/admin/configuration/{key}` | Platform admin | None | `{key, value, updated_at}` |
| `PATCH /api/v1/admin/configuration/{key}` | Platform admin | `{value}` | `{key, value, updated_at}` |
| `GET /api/v1/admin/membership-plans` | Platform admin | Query `{status?}` | `{items: MembershipPlan[], next_cursor:null}`; each plan includes `price_amount`, `currency`, `generation_quota`, `assistant_quota`, and `purchasable`. |
| `POST /api/v1/admin/membership-plans` | Platform admin | `{code, name, duration_days, entitlement_codes, price_amount, currency:"CNY", generation_quota, assistant_quota, purchasable:false}` | `201 MembershipPlan`; price must be positive, duration `1..3650`, generation quota `0..10000`, and assistant quota `0..1000000`. |
| `PATCH /api/v1/admin/membership-plans/{membership_plan_id}` | Platform admin | `{price_amount?, currency?, duration_days?, generation_quota?, assistant_quota?, purchasable?}` | `MembershipPlan`; setting `purchasable:true` requires a published plan. Archiving always disables purchase. |
| `GET /api/v1/admin/membership-purchases` | Platform admin | Query `{status?:"pending_payment"\|"paid"\|"closed"}` | `{items:[{id, user_id, membership_plan_id, plan_name, amount, currency, duration_days, generation_quota, assistant_quota, status, payment_status, authorization_status, failure_code?, paid_at?, authorized_at?, valid_from?, valid_until?, created_at}]}`; excludes payment numbers, signatures, callback payloads, and provider transaction IDs. |
| `POST /api/v1/admin/membership-purchases/{purchase_id}:retry-authorization` | Platform admin | `{}` | Redacted membership-purchase audit fact. Only a `payment_status:"paid"` purchase not yet authorized can be retried; other states return `409 AUTHORIZATION_RETRY_NOT_ALLOWED`. |
| `GET /api/v1/admin/integrations` | Platform admin | None | `{items:[{name, configured, healthy, last_checked_at, error_code?}]}` |
| `POST /api/v1/admin/integrations/{integration_name}:check` | Platform admin | `{}` | `202 Job` or `{name, healthy, checked_at, error_code?}` |

## Realtime, Events, And Technical Dependency Map

| Method and path | Authorization | Request schema | Response schema |
|---|---|---|---|
| `POST /api/v1/realtime-tickets` | User with access to the requested resource | `{resource_type:"itinerary"\|"conversation", resource_id}` | `201 {resource_type, resource_id, ticket, expires_in}` |

`resource_type="itinerary"` binds the single-use ticket to `wss://<host>/api/v1/ws/itineraries/{resource_id}?ticket=<ticket>`; `resource_type="conversation"` binds it to `wss://<host>/api/v1/ws/conversations/{resource_id}?ticket=<ticket>`. `ticket` expires after `expires_in` seconds (60), cannot be reused, is never logged, and active resource access is rechecked before the socket is accepted. For chat, REST persists and commits the canonical message before publishing `message.created` to Redis channel `chat:conversation:{conversation_id}`; publish failure does not roll back the message. Each API process subscribes through Redis Pub/Sub, sends heartbeat `ping` frames, and cleans up its subscription on disconnect. Clients answer `pong`, obtain a fresh ticket after disconnect, and merge HTTP history by message/client-message ID after reconnect. Itinerary messages use `{type, operation_id, base_version, operation_type, target, payload}`; committed broadcasts use `itinerary.operation.applied`.

All aggregate writes create their Outbox event in the same MySQL transaction. The mandatory envelope and event catalog are `docs/contracts/领域事件.md`; publishers require RabbitMQ confirms and consumers deduplicate by `event_id`.

The verbatim shared nine-step technical dependency map is `docs/contracts/说明.md#technical-dependency-map`. It controls implementation integration order only; every route above remains in scope.
