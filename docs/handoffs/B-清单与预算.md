# Agent B Handoff: Checklist and Budget

## Scope

Implemented itinerary preparation and expense-management capabilities. The work does not alter `ItineraryEvent` ordering, route recalculation behavior, or map components.

## Completed User Capabilities

- Travelers can create, edit, delete, and mark checklist items complete.
- Checklist items are returned and displayed grouped by category.
- Travelers can create, edit, and delete budget items.
- Budget amounts require non-negative decimal values with up to two decimal places.
- Budget creation validates an allowlist of ISO 4217 currency codes and normalizes them to uppercase.
- Budget totals are grouped by currency; values in different currencies are never combined.
- The consumer itinerary workspace now shows checklist and budget management below the existing map/place context. Owners and editors can change data; viewers see it read-only.

## Modified Files

### Backend

- `backend/app/modules/trip_support/__init__.py`
- `backend/app/modules/trip_support/models.py`
- `backend/app/modules/trip_support/schemas.py`
- `backend/app/modules/trip_support/service.py`
- `backend/app/modules/trip_support/router.py`
- `backend/app/modules/itineraries/models.py`
- `backend/app/modules/itineraries/router.py`
- `backend/alembic/versions/20260804_0006_trip_support.py`
- `backend/tests/trip_support/__init__.py`
- `backend/tests/trip_support/test_router.py`

### Consumer Frontend

- `frontend-c/src/features/itineraries/tripSupportApi.ts`
- `frontend-c/src/features/itineraries/components/TripSupportPanel.vue`
- `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue`

## API, Permissions, and Errors

Routes are included from the established itinerary router, so the externally available paths are:

- `GET /api/v1/itineraries/{itinerary_id}/checklists`
- `POST /api/v1/itineraries/{itinerary_id}/checklists`
- `PATCH /api/v1/itineraries/{itinerary_id}/checklists/{item_id}`
- `DELETE /api/v1/itineraries/{itinerary_id}/checklists/{item_id}`
- `GET /api/v1/itineraries/{itinerary_id}/budgets`
- `POST /api/v1/itineraries/{itinerary_id}/budgets`
- `PATCH /api/v1/itineraries/{itinerary_id}/budgets/{item_id}`
- `DELETE /api/v1/itineraries/{itinerary_id}/budgets/{item_id}`

Permissions:

- Owner and accepted collaborator can list checklists and budgets.
- Owner and accepted `editor` collaborator can create, update, and delete items.
- A missing resource, unavailable itinerary, or insufficient permission returns `404` with error code `TRIP_RESOURCE_NOT_FOUND`; this follows the existing itinerary pattern of not exposing inaccessible resources.
- Invalid amounts and currencies return the existing `422 VALIDATION_ERROR` envelope.

Contract deviations to review:

- The target API contract describes item updates at global `/checklists/{item_id}` and `/budgets/{item_id}` paths. Those require global router registration, but `backend/app/api/router.py` was explicitly reserved. Therefore updates are nested under their itinerary routes above.
- The list contract in `docs/API设计.md` shows one `total_amount` and `currency`. Implementation returns `totals: [{currency, total_amount}]` to prevent invalid cross-currency sums.

## Data Model and Migration

- `ChecklistItem` maps to `checklist_items`: UUID ID, itinerary FK with cascade, category, content, checked flag, source, and timestamps.
- `BudgetItem` maps to `budget_items`: UUID ID, itinerary FK with cascade, category, `DECIMAL(12,2)` amount, ISO currency, optional description, and timestamps.
- Migration `20260804_0006_trip_support` depends on `20260801_0005`, creates both tables, FK indexes, and the `amount >= 0` check constraint. Downgrade drops both tables.
- `backend/app/modules/itineraries/models.py` imports the trip-support model module at its end. This lets the pre-existing Alembic import of itinerary models populate `Base.metadata` without changing reserved `backend/alembic/env.py`.

## Verification Performed

- `cd backend; py -3 -m pytest tests/trip_support/test_router.py tests/itineraries/test_router_operations.py -q`
  - Passed: `2 passed`.
- `cd backend; py -3 -m compileall -q app/modules/trip_support`
  - Passed.
- Metadata registration check:
  - `py -3 -c "from app.models.base import Base; import app.modules.itineraries.models; assert {'checklist_items', 'budget_items'} <= set(Base.metadata.tables)"`
  - Passed.
- `cd frontend-c; npm run typecheck`
  - Passed.
- `cd frontend-c; npm run build`
  - Passed. Existing Rollup pure-comment and chunk-size warnings remain.
- `cd frontend-c; npm run test -- --run src/features/itineraries/stores/itinerary.test.ts`
  - Passed: `1 passed`.
- `git diff --check` over Agent B files
  - Passed.
- Impeccable detector over changed itinerary UI files
  - Passed: no findings.

## Unfinished Items and Risks

- Alembic migration was not applied, downgraded, and re-applied. Docker Desktop's Linux engine was unavailable, so Compose MySQL could not be reached. Main agent should run:
  - `cd backend; alembic upgrade head`
  - `cd backend; alembic downgrade -1`
  - `cd backend; alembic upgrade head`
- Existing test `tests/itineraries/test_versioned_operations.py::test_recalculate_route_persists_real_route_segments` fails independently of this work: after `recalculate_route`, no `RouteSegment` is persisted. Agent B did not modify `ItineraryService`, event ordering, route calculation, or map code per scope.
- Currency validation uses an intentional supported-code allowlist: `CNY`, `USD`, `EUR`, `GBP`, `JPY`, `KRW`, `HKD`, `TWD`, `THB`, `SGD`, `AUD`, `CAD`, `NZD`, `CHF`, `AED`. Broaden this list or introduce a canonical currency registry if product requirements need all ISO 4217 currencies.
- There is no frontend component test for the new panel; end-to-end/browser validation after the backend migration is recommended.

## Shared File Coordination

Agent B did not modify these reserved/shared files:

- `backend/app/api/router.py`
- `backend/app/core/settings.py`
- `backend/alembic/env.py`
- `docker-compose.yml`
- `nginx/nginx.conf`
- `frontend-c/src/services/api.ts`
- `frontend-b/src/services/api.ts`

The main agent should decide whether to accept the nested update routes or register the global contract paths in `backend/app/api/router.py`. If global paths are required, move or additionally expose the update/delete endpoints through the shared API router and update `tripSupportApi.ts` accordingly.
