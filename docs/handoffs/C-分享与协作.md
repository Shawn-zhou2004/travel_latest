# Agent C Handoff: Sharing And Collaboration

## Scope

Agent C implemented itinerary sharing and multi-user collaboration without modifying the existing versioned mutation implementation. The implementation relies on the pre-existing itinerary permission extension points (`_can_read` and `_can_edit`).

The following shared files were explicitly not modified by Agent C:

- `backend/app/api/router.py`
- `backend/app/core/settings.py`
- `backend/alembic/env.py`
- `docker-compose.yml`
- `nginx/nginx.conf`
- `frontend-c/src/services/api.ts`
- `frontend-b/src/services/api.ts`

## Completed User Capabilities

- Owners can create a public, read-only itinerary share link.
- Share tokens are generated with 256 bits of URL-safe entropy and only their SHA-256 hashes are persisted.
- A share link is rejected when its token is invalid, revoked, expired, or bound to a different itinerary.
- Owners can revoke share links.
- Owners can invite registered users as `viewer` or `editor` collaborators.
- Invited users can accept their invitation. Repeating an accepted invitation request is idempotent.
- Owners, accepted editors, and accepted viewers receive `access_role` in authenticated itinerary detail responses.
- Owners and editors retain write access through the existing `_can_edit` authorization path.
- Accepted viewers can read but server-side writes are rejected with `FORBIDDEN`.
- Concurrent owner/editor writes retain the existing version conflict behavior. A stale base version returns `VERSION_CONFLICT` with the current snapshot.
- Consumer workspaces hide or disable write controls for viewers.
- Public shared itineraries have a dedicated unauthenticated, read-only page at `/shared/itineraries/:itineraryId?token=...`.
- Owners can create a public link and a collaborator invitation URL from the itinerary workspace.

## Files Changed By Agent C

Backend:

- `backend/app/modules/itineraries/schemas.py`
- `backend/app/modules/itineraries/service.py`
- `backend/app/modules/itineraries/router.py`
- `backend/tests/itineraries/test_collaboration.py` (new)

Consumer frontend:

- `frontend-c/src/features/itineraries/api.ts`
- `frontend-c/src/features/itineraries/stores/itinerary.ts`
- `frontend-c/src/features/itineraries/components/Timeline.vue`
- `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue`
- `frontend-c/src/features/itineraries/pages/SharedItineraryPage.vue` (new)
- `frontend-c/src/router/index.ts`

Important worktree note: the repository already contained broad uncommitted and untracked implementation work, including the entire itinerary module and migration files. The list above identifies Agent C's intended logical changes, not exclusive Git ownership of every file.

## API And Permission Changes

All endpoints are under `/api/v1` through the existing itinerary router registration.

| Method | Path | Authorization | Result |
|---|---|---|---|
| `GET` | `/itineraries/{itinerary_id}` | Owner or accepted collaborator | Adds `access_role`: `owner`, `editor`, or `viewer`. |
| `GET` | `/itineraries/{itinerary_id}/shared?share_token=...` | Valid share token | Returns a read-only itinerary snapshot with `access_role: "viewer"`. |
| `POST` | `/itineraries/{itinerary_id}/share-tokens` | Owner | Creates a token. Request: `{expires_at?}`. Response includes `{id, share_url, token, expires_at}`. The plaintext token is returned only at creation time. |
| `DELETE` | `/itineraries/{itinerary_id}/share-tokens/{token_id}` | Owner | Revokes the token and returns `204`. |
| `POST` | `/itineraries/{itinerary_id}/collaborators` | Owner | Invites an existing user. Request: `{user_id, role}` where role is `viewer` or `editor`. |
| `PATCH` | `/itineraries/{itinerary_id}/collaborators/{collaborator_id}` | Owner | Updates `{role?, invite_status?}`. Supported owner-set statuses are `pending` and `revoked`. |
| `POST` | `/itineraries/{itinerary_id}/collaborators/{collaborator_id}:accept` | Invited user | Accepts a pending invitation; repeated accept is idempotent. |

New explicit error codes:

- `SHARE_LINK_UNAVAILABLE` (`404`): invalid, revoked, expired, or mismatched public link.
- `SHARE_TOKEN_NOT_FOUND` (`404`): token does not exist for this itinerary or caller is not owner.
- `COLLABORATOR_UNAVAILABLE` (`404`): itinerary, target user, collaborator record, or invitation is unavailable to the caller.

Existing operation results are unchanged:

- `FORBIDDEN`: viewer or unaccepted collaborator tries a versioned write.
- `VERSION_CONFLICT`: an owner/editor submits a stale `If-Match-Version`.

## Data Model And Alembic

No schema change was created by Agent C.

The pre-existing itinerary aggregate migration `backend/alembic/versions/20260801_0002_itinerary_aggregate.py` already creates the required tables:

- `trip_collaborators`
  - Unique `(itinerary_id, user_id)`.
  - `role` constrained to `viewer` or `editor`.
  - `status` constrained to `pending`, `accepted`, or `revoked`.
- `trip_share_tokens`
  - Unique `token_hash`.
  - Optional `expires_at` and `revoked_at`.

The ORM models are present in `backend/app/modules/itineraries/models.py`. `backend/alembic/env.py` already imports itinerary models and was not modified.

Alembic migration verification was not run because this task did not add a migration and no Compose MySQL lifecycle was started during this handoff. Main agent should run the repository-required MySQL verification before release:

```powershell
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

## Verification Evidence

Passed:

```text
backend: python -m pytest tests/itineraries/test_collaboration.py tests/itineraries/test_router_operations.py
3 passed

frontend-c: npm run typecheck
passed

frontend-c: npm run test -- --run src/features/itineraries/stores/itinerary.test.ts
1 passed

frontend-c: npm run build
passed
```

`git diff --check` reported no whitespace errors in Agent C's scoped files. Git did print pre-existing CRLF conversion warnings for repository files.

The initial broader backend run was:

```text
python -m pytest tests/itineraries/test_collaboration.py tests/itineraries/test_versioned_operations.py tests/itineraries/test_router_operations.py
9 passed, 1 failed
```

The failure was the pre-existing `tests/itineraries/test_versioned_operations.py::test_recalculate_route_persists_real_route_segments`: after a successful route recalculation result, the test's direct query found no `RouteSegment`. This failure does not exercise share links, collaborators, access roles, or the new permission checks. It remains a release blocker for a full itinerary-suite green run and should be triaged by the itinerary/versioning owner.

Build warnings to retain:

- Rollup removed malformed `/* #__PURE__ */` annotations in `@vueuse/core`.
- Consumer bundle remains larger than Vite's 500 kB warning threshold.

## Known Risks And Unfinished Items

- Invitation UX currently requires a registered user's UUID, because the existing user model has no email/nickname lookup endpoint. A production invitation flow should add a user discovery or notification contract owned by the identity/notifications team.
- The frontend creates share links but currently has no owner-facing list of active tokens or UI action to revoke a specific token. The API supports revocation.
- Public sharing uses a query-string token. Avoid logging full request URLs in production access logs and analytics, because query strings can expose bearer tokens. Consider a fragment-based handoff/client exchange or request log redaction in the platform gateway.
- The public `share_url` returned by the API is relative (`/shared/itineraries/...`). The consumer client resolves it against `window.location.origin`; non-browser clients must do the same against their public web origin.
- `POST /share-tokens` permits an arbitrary count of simultaneously valid tokens. Token count limits or a one-active-token policy are not implemented.
- No browser acceptance run was performed for the dialog, copied links, mobile layout, or public page. Run bounded UI acceptance before release.
- There is no audit event/outbox event for creation, revocation, invitation, or acceptance. Add these only if the platform event contract requires collaboration auditability.

## Required Coordination On Shared Files

- `frontend-c/src/router/index.ts` already had unrelated route changes in the working tree before Agent C's shared route was added. Main agent should merge the single `/shared/itineraries/:itineraryId` route without discarding concurrent route work.
- `backend/app/modules/itineraries/router.py` is already included by `backend/app/api/router.py`; no router registration change is required. Keep this file untouched per the shared-file restriction.
- `frontend-c/src/services/api.ts` remains unchanged. Its default `Authorization` header is harmless for the public endpoint, but its error normalization maps FastAPI's current `detail` response format to `REQUEST_FAILED`; main agent may want to align global API error envelopes separately.
- `backend/alembic/versions/20260801_0002_itinerary_aggregate.py` is an untracked existing migration in this worktree. Ensure it is included in the final migration chain before deployment; Agent C did not edit it.
- `backend/app/modules/itineraries/models.py` already contained `TripCollaborator` and `TripShareToken`; Agent C used those models without changing the schema.
