# Agent C Handoff: Providers And Experiences

## Status

Implementation initially stopped after reading the required module brief and comparing it with the current source baseline. The shared routing and persistence blockers were subsequently integrated by the final integrator; frontend delivery and MySQL migration verification remain outstanding.

The required brief is `docs/agent-briefs/C-服务商与体验.md`. It states that `GET /api/v1/admin/providers` deliberately returns `501 PROVIDER_REVIEW_NOT_IMPLEMENTED` and that this honest placeholder must not be replaced with fabricated data. The requested outcome requires the existing management UI to use a real provider-review API, but the two required integration files are forbidden:

- `backend/app/api/router.py` is the only `/api/v1` router assembly point.
- `backend/app/modules/admin/router.py` owns the existing `GET /admin/providers` `501` endpoint.

Registering a new providers router is impossible without changing `backend/app/api/router.py`. Registering a second `GET /admin/providers` route while retaining the existing admin route is not safe: FastAPI route matching would retain the earlier `501` handler. Replacing or delegating the existing endpoint requires modifying `backend/app/modules/admin/router.py`, which is outside the allowed paths.

Per `docs/agent-briefs/说明.md`, no silent shared-interface replacement was made. The implementation must not be advanced or claimed as integrated until the main agent resolves the ownership boundary below.

## Work Produced Before Stop

The following unregistered backend module skeleton was created before the required brief was read:

- `backend/app/modules/providers/__init__.py`
- `backend/app/modules/providers/models.py`
- `backend/app/modules/providers/schemas.py`
- `backend/app/modules/providers/service.py`
- `backend/app/modules/providers/router.py`
- `backend/tests/providers/test_services.py`

It is not registered and therefore exposes no runtime API. No frontend implementation was started. No migration was created. The main agent should review the skeleton before deciding whether to retain, revise, or remove it.

## Proposed Model Design

The skeleton models the following provider-owned tables, matching `docs/数据库设计.md` ownership:

| Table | Main fields and constraints | Required indexes / foreign keys |
|---|---|---|
| `providers` | `applicant_id`, `provider_type`, `legal_name`, `contact`, qualification and claimed-POI JSON payloads, `status` (`pending_review`, `approved`, `rejected`), `review_reason`, `reviewed_by`, `reviewed_at` | FK applicant/reviewer to `users`; indexes on applicant, status, reviewer. |
| `provider_reviews` | immutable review fact: provider, actor, previous status, result status, reason, timestamp | FK to provider and user; provider index. |
| `experience_services` | provider, title, description, verified POI snapshot, price amount/currency, cancellation policy, `status` (`draft`, `published`, `archived`) | FK provider; provider and status indexes. |
| `experience_sessions` | experience, starts_at, capacity, reserved_count, optional price override, `status` (`scheduled`, `cancelled`, `completed`) | FK experience; start-time index; checks `capacity > 0` and `0 <= reserved_count <= capacity`. |
| `experience_bookings` | session, user, traveler_count, independent `status` (`reserved`, `verified`, `cancelled`), verification code, verified timestamp | FK session/user; unique `(experience_session_id, user_id)`; checks traveler count positive. |
| `experience_reviews` | booking, user, rating, body | FK booking/user; unique booking review; rating check 1 through 5. |

The migration must also import `app.modules.providers.models` into `backend/alembic/env.py`, create all tables/indexes/FKs/check constraints additively, and provide a reverse drop order: reviews, bookings, sessions, experiences, reviews, providers. This work is deliberately not performed because migrations and `env.py` are forbidden.

## Intended API And Permissions

The unregistered router proposes the following target paths. These are not currently active APIs.

| Method | Path | Required actor | Notes |
|---|---|---|---|
| `POST` | `/provider-applications` | Consumer | Creates `pending_review` application. |
| `GET` | `/admin/providers` | `platform_admin` | Lists review records. Conflicts with existing admin `501` route. |
| `PATCH` | `/admin/providers/{provider_id}` | `platform_admin` | `approved` / `rejected` plus mandatory reason; writes `provider_reviews`. Conflicts with absent current admin PATCH implementation. |
| `POST` | `/provider/experiences` | Provider staff scoped to request `provider_id` | Requires approved provider and verified AMap POI. |
| `POST` | `/provider/experiences/{experience_id}/sessions` | Scoped provider staff | Creates capacity-controlled session. |
| `POST` | `/experience-bookings` | Consumer | Creates independent reservation, not a TravelOrder. |
| `POST` | `/provider/experience-bookings/{booking_id}:verify` | Scoped provider staff | One-time verification with code. |
| `POST` | `/experience-bookings/{booking_id}/evaluations` | Booking owner after verification | One evaluation per booking. |

Provider scope proposal: a user needs `provider_admin` or `provider_staff` role plus `UserRole.scope_key == provider_id`. The service checks this before creating an experience, creating sessions, or verifying a booking. A scope mismatch produces `PROVIDER_SCOPE_FORBIDDEN`.

## Intended State Machines

Provider application:

```text
pending_review -> approved
pending_review -> rejected
```

Experience:

```text
draft -> published -> archived
```

Session:

```text
scheduled -> completed
scheduled -> cancelled
```

Booking, intentionally independent from orders and payments:

```text
reserved -> verified
reserved -> cancelled
```

Review creation requires `booking.status == verified`; it does not mutate the booking state.

## Intended Error Codes

- `FORBIDDEN`
- `PROVIDER_SCOPE_FORBIDDEN`
- `PROVIDER_NOT_FOUND`
- `PROVIDER_NOT_APPROVED`
- `INVALID_PROVIDER_TRANSITION`
- `MAP_UNAVAILABLE`
- `EXPERIENCE_NOT_FOUND`
- `SESSION_NOT_FOUND`
- `SESSION_UNAVAILABLE`
- `SESSION_CAPACITY_EXCEEDED`
- `DUPLICATE_BOOKING`
- `BOOKING_NOT_FOUND`
- `INVALID_VERIFICATION_CODE`
- `BOOKING_NOT_VERIFIABLE`
- `BOOKING_NOT_COMPLETED`
- `DUPLICATE_REVIEW`

## Required Main-Agent Integration

1. Decide ownership of `/api/v1/admin/providers`.
   - Recommended: modify `backend/app/modules/admin/router.py` to replace its `501` implementation with a delegation to `ProviderService`, preserving the existing admin router as the endpoint owner.
   - Alternative: remove the existing admin endpoint and register the providers router through `backend/app/api/router.py`.
   - Do not register two identical `GET /admin/providers` routes.
2. Import and include `app.modules.providers.router.router` from `backend/app/api/router.py` for all non-admin providers routes.
3. Add `app.modules.providers.models` to `backend/alembic/env.py` and create a single migration implementing the model design above.
4. Confirm whether provider-facing endpoints authenticate with the existing admin-audience token (`CurrentAdmin`) or need a provider B-end audience/dependency. The current source has only consumer/admin audience dependencies. The skeleton uses `CurrentAdmin` for provider staff because it is the only available B-end dependency, which may not match the intended token audience contract.
5. Connect the existing management UI service (`frontend-b/src/features/admin/services/operations.ts`) only after step 1 exposes a real endpoint. It already calls the target `/admin/providers`; changing it now would not resolve the backend `501`.
6. Add provider and consumer frontend feature pages after runtime API ownership is resolved. No frontend routes were added during the blocked state.

## Integration Record (2026-08-04)

- `backend/app/api/router.py` now registers the non-admin providers router.
- `backend/app/modules/admin/router.py` remains the sole owner of `/api/v1/admin/providers`; its former `501` now delegates list and review operations to `ProviderService`, and review writes an `AdminAction`.
- `backend/alembic/env.py` imports provider models and `20260804_0009_follows_and_providers` creates provider, review, experience, session, booking and evaluation tables.
- Qualification and claimed-POI fields use MySQL JSON, rather than the skeleton's serialized text proposal.
- Provider service workflow test passes. The application accepts the existing `CurrentAdmin` audience for provider staff because no separate provider audience currently exists; introducing one remains an authentication-contract follow-up.
- Compose MySQL was not running during integration, so the migration upgrade/downgrade/upgrade verification is still required.

## Order Boundary

No code writes `backend/app/modules/orders/` data or invokes its state machine. Booking is an independent reservation with `travel_order_id` intentionally absent. A future order link requires a cross-module contract defining when a booking is created, capacity reservation expiry/cancellation semantics, payment failure behavior, and outbox events. Do not infer booking verification from payment success.

## Tests And Verification

No test, typecheck, frontend test, frontend build, migration, or full module verification was run after the stop condition was discovered. The unregistered test skeleton is not accepted evidence.

`git diff --check` for this handoff has not yet been run by this document's author. Main agent should run it after deciding whether the skeleton is retained.

## Risks

- The generated backend files cannot work in production without router registration and an Alembic migration.
- The current service skeleton stores qualification asset IDs and claimed POI IDs as serialized text; main agent should prefer a JSON column in the migration/model if project migration policy accepts it.
- Current direct API implementation uses a `provider_id` query parameter for some provider operations. This should be replaced with a clear provider-profile or path-scoped contract during integration.
- No outbox/admin audit integration was connected to the existing `AdminAction` model because it is owned by the admin module and outside the allowed edit scope. The proposed `provider_reviews` table retains provider-domain audit facts, but final admin audit requirements still need explicit integration.
