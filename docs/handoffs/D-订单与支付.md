# D Orders And Payments Handoff

## Delivery Status

No order/payment implementation was shipped in this pass. The module brief and current source establish a different baseline from the target-only `docs/API设计.md`: current payment creation and callback endpoints intentionally expose the `PAYMENT_NOT_CONFIGURED` unavailable state, while order detail, refunds, callback verification, and a configured Alipay sandbox adapter do not yet exist.

The requested full payment and refund loop cannot be added safely inside the allowed file set because it requires persistent schema changes, and creating or changing `backend/alembic/versions/` is explicitly prohibited. Per `docs/agent-briefs/说明.md`, implementation was stopped rather than silently introducing an ORM/schema mismatch or changing shared integration files.

## Current User Capabilities

- Supplier search returns an explicit `SUPPLIER_UNAVAILABLE` result when no authorized supplier adapter is configured.
- Order creation validates offer availability and expiration, requires `Idempotency-Key`, preserves the offer snapshot, and keeps order/payment/fulfillment statuses independent.
- Consumer users can list their own orders and query payment facts for their own order.
- Platform administrators can query payment facts through the existing shared authorization behavior.
- Payment creation currently returns a clear unavailable result and never fabricates payment success.
- The consumer order list renders the independent status triplet and does not claim fulfillment after payment.

## Actual Current APIs

| Method | Path | Current behavior | Permission / idempotency |
| --- | --- | --- | --- |
| `POST` | `/api/v1/travel-search-jobs` | Supplier search; default adapter reports unavailable | Consumer; `Idempotency-Key` |
| `GET` | `/api/v1/travel-search-jobs/{job_id}` | Own search job | Consumer owner |
| `GET` | `/api/v1/travel-search-jobs/{job_id}/offers` | Own offer snapshots | Consumer owner |
| `POST` | `/api/v1/travel-orders` | Creates from a valid, unexpired offer | Consumer; `Idempotency-Key` |
| `GET` | `/api/v1/travel-orders` | Lists own orders | Consumer owner |
| `POST` | `/api/v1/travel-orders/{order_id}/payments` | Current unavailable placeholder; transitions to failed with `PAYMENT_NOT_CONFIGURED` | Consumer owner; currently missing required payment `Idempotency-Key` |
| `POST` | `/api/v1/travel-orders/{order_id}:query-payment` | Reads order/payment facts | Owner or `platform_admin` |
| `POST` | `/api/v1/payments/alipay/callback` | Current unavailable placeholder | Callback endpoint; no verification configured |

Known implemented error codes include `OFFER_NOT_FOUND`, `OFFER_UNAVAILABLE`, `OFFER_EXPIRED`, `IDEMPOTENCY_CONFLICT`, `PAYMENT_NOT_ALLOWED`, `PAYMENT_NOT_CONFIGURED`, `INVALID_ORDER_TRANSITION`, and `FORBIDDEN`.

## Target Contract Differences

`docs/API设计.md` describes full-scope target behavior, not current implementation. The following target APIs do not currently exist and were not added due to the persistence/migration blocker:

- `GET /api/v1/travel-orders/{order_id}` for owner/admin order detail including offer snapshot, payments, and refunds.
- `POST /api/v1/travel-orders/{order_id}/payments` with a configured sandbox checkout payload and payment creation idempotency.
- `POST /api/v1/travel-orders/{order_id}/refunds` with payment-currency and refundable-balance enforcement.
- Refund-status query endpoint required by the task; the target API design does not specify a standalone path, so the integrator must select either order detail embedded refunds or `GET /travel-orders/{order_id}/refunds` and document it.
- Verified `POST /api/v1/payments/alipay/callback` behavior with signature, merchant number, amount, currency, duplicate callback, and state-transition checks.

## State Machine Required For Integration

Existing canonical states remain authoritative:

- Order: `PENDING_CONFIRMATION` -> `PAYING` -> `PAID_PENDING_FULFILLMENT` -> `CONFIRMED`, with independent failure/refund branches `FAILED`, `REFUNDING`, `REFUNDED`, `CLOSED`.
- Payment: `pending`, `paying`, `paid`, `failed`, `refunding`, `refunded`.
- Fulfillment: `pending_confirmation`, `confirming`, `confirmed`, `failed`, `not_supported`.

Integration rules:

- The server, never a browser redirect, success screen, or client request field, transitions to `paid`.
- A verified callback may transition `PAYING/paying/pending_confirmation` only to `PAID_PENDING_FULFILLMENT/paid/pending_confirmation`; it must not infer fulfillment.
- Refund requests must use `Idempotency-Key`, require a paid payment, preserve currency, and reject values greater than paid amount minus every non-failed refund.
- Callback processing must atomically persist the callback audit before/with verification outcome, deduplicate on provider callback identity, verify the provider signature, merchant payment number, amount, currency, and legal current state.

## Required Migration For Main Integrator

No Alembic revision was created or changed by Agent D. Before enabling any full loop, create an additive MySQL revision owned by the integration phase to add:

- `payment_records.idempotency_key VARCHAR(128) NOT NULL` and `UNIQUE(order_id, idempotency_key)`.
- `refund_records.idempotency_key VARCHAR(128) NOT NULL`, `currency CHAR(3) NOT NULL`, `reason VARCHAR(500) NOT NULL`, and `UNIQUE(payment_id, idempotency_key)`.
- `payment_callback_events.signature_valid` and `processing_status`, plus required recorded verification facts such as callback amount/currency if not captured immutably in `raw_payload`.
- Any required indexes for callback lookup and refund-balance aggregation.

The migration must update MySQL check constraints only if adding a state not already covered by the canonical enum, and must be verified with `alembic upgrade head`, `alembic downgrade -1`, and `alembic upgrade head` against Compose MySQL.

## Adapter And Credentials Requirements

- Place the sandbox adapter under `backend/app/integrations/alipay/`.
- Read signing keys, application IDs, gateway configuration, and any mock secret exclusively from environment variables. Do not place values in source, tests, snapshots, `.env` commits, or this report.
- Use a disabled/unavailable adapter when required environment values are absent. It must return `PAYMENT_NOT_CONFIGURED` or a clearly mapped `503`, without creating a successful checkout/payment result.
- A controlled mock adapter must require a server-held signature secret and must use an HMAC or equivalent verifiable signature; it may not accept arbitrary browser callback payloads as payment facts.
- Supplier adapters remain under `backend/app/integrations/suppliers/`; their unavailability must remain explicit and must not produce bookable fabricated offers.

## Tests Already Present

No new test was added in this blocked pass. Existing focused order tests cover:

- Expired offer rejects order creation (`OFFER_EXPIRED`).
- Order creation is idempotent for a user/key/offer combination.
- Existing unconfigured payment flow returns a failed payment state.
- Immutable supplier offer persistence.

Required tests before integration acceptance:

- Order idempotency conflict on key reuse with another offer.
- Payment creation idempotency and key-conflict behavior.
- Missing payment configuration produces a non-success unavailable result without pretending payment was accepted.
- Callback signature failure, duplicate callback, unknown payment, amount mismatch, currency mismatch, invalid provider status, and invalid state transition.
- Owner/non-owner/admin authorization for detail, payment query, payment creation, and refunds.
- Refund idempotency, currency mismatch, excess amount, cumulative partial-refund cap, and illegal order/payment transition.
- Frontend detail rendering for loading, unavailable payment, payment query refresh, refund failure, and no false payment-success state after redirect.

## Files Changed In This Pass

- Added `docs/handoffs/D-订单与支付.md` only.

No implementation changes remain in `backend/app/modules/orders/`, `backend/app/integrations/alipay/`, `backend/app/integrations/suppliers/`, `backend/tests/orders/`, `frontend-c/src/features/orders/`, or `frontend-c/src/router/index.ts` from this pass.

## Required Shared-File Coordination And Risks

- The final integrator must register any new adapter-enabled endpoint behavior through the existing shared API composition only after approving the concrete module contract; `backend/app/api/router.py` is protected and was not changed.
- The consumer shared API client is protected; feature-local API types can be extended after backend routes are integrated, but shared error/refresh behavior must not be changed for payment work.
- The current order list is an array while the target contract calls for cursor pagination. This is another source/target mismatch that must be resolved intentionally when detail/refund routes are integrated.
- The current `POST /travel-orders/{order_id}/payments` does not require `Idempotency-Key`, conflicting with the global target write rule. Correcting it depends on adding the payment idempotency persistence constraint above.
- The current failure placeholder consumes the order by transitioning it to `FAILED`. The configured payment design must be agreed before replacing that behavior, because a missing payment configuration should be unavailable without an irreversible client-side success/failure interpretation.
- Browser and full test/build verification were not run because no implementation was shipped after the required baseline-conflict stop.
