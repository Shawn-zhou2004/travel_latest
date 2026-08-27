# Agent B Handoff: Companion Requests and Chat

## Implemented Capabilities

### Companion requests

- Public listing remains limited to requests with `status == open` and `review_status == approved`.
- Owners can list their own requests, edit an open request, close it, or cancel it.
- Only request owners can view a request's private application list or accept/reject an application.
- Applicants cannot apply to their own request.
- Repeating an application returns the existing application, preserving idempotency through the existing `(request_id, applicant_id)` unique constraint.
- Applicants can withdraw only a pending application.
- Owners can accept or reject only pending applications while the request is open.
- Acceptance creates a `companion_group` conversation and active membership rows for owner and applicant in the same transaction, then closes the request.
- Companion lifecycle changes create Outbox events. Community does not write notification rows directly.

### Chat

- `GET /conversations` returns the authenticated user's active conversation list, unread counts, last message, and a stable cursor.
- `GET /conversations/{conversation_id}/messages` performs server-validated history recovery with stable ascending `(created_at, id)` cursor ordering and marks the returned page as read.
- Messages retain server-side idempotency on `(conversation_id, sender_id, client_message_id)`.
- Non-members and members with `left_at` set cannot read or send messages.
- Direct-contact blocks prevent new direct conversations and new messages in an existing direct conversation. Existing active direct members can still read historic messages; block does not erase history.
- Users can unblock a user and leave a conversation. WebSocket remains an enhancement; HTTP list/history works without it.
- Message delivery remains Outbox-based through `message.created`; no direct notification-table writes were added.

### Consumer UI

- Companion page now loads public requests, owned requests, and the current user's applications.
- Owners can view applications and accept/reject them; applicants can withdraw pending applications; owners can close/cancel open requests.
- Chat page now fetches an HTTP conversation list and HTTP history, displays unread counts, and creates local `sending`/`failed` message states during send failures.

## Changed Files

### Backend

- `backend/app/modules/community/schemas.py`
- `backend/app/modules/community/service.py`
- `backend/app/modules/community/router.py`
- `backend/app/modules/chat/schemas.py`
- `backend/app/modules/chat/service.py`
- `backend/app/modules/chat/router.py`
- `backend/tests/community/test_services.py`
- `backend/tests/chat/test_services.py`

### Consumer Frontend

- `frontend-c/src/features/community/companionApi.ts`
- `frontend-c/src/features/community/CompanionsPage.vue`
- `frontend-c/src/features/community/types.ts`
- `frontend-c/src/features/chat/api.ts`
- `frontend-c/src/features/chat/ChatPage.vue`
- `frontend-c/src/features/chat/ChatHistory.vue`

## API, Permissions, and Errors

Existing routes retained:

- `GET /api/v1/companion-requests` public approved/open requests.
- `POST /api/v1/companion-requests` authenticated consumer creates a request.
- `POST /api/v1/companion-requests/{request_id}/applications` authenticated consumer applies idempotently.
- `POST /api/v1/companion-applications/{application_id}:accept|reject` owner decision.
- `POST /api/v1/conversations/direct`, `POST /api/v1/conversations/{conversation_id}/messages`, and `POST /api/v1/blocks`.

Added module routes, pending shared API router integration:

- `GET /api/v1/companion-requests/mine`
- `PATCH /api/v1/companion-requests/{request_id}`
- `POST /api/v1/companion-requests/{request_id}:close`
- `POST /api/v1/companion-requests/{request_id}:cancel`
- `GET /api/v1/companion-requests/{request_id}/applications`
- `GET /api/v1/companion-applications/mine`
- `POST /api/v1/companion-applications/{application_id}:withdraw`
- `GET /api/v1/conversations?cursor=&limit=`
- `GET /api/v1/conversations/{conversation_id}/messages?cursor=&limit=`
- `DELETE /api/v1/blocks/{user_id}`
- `POST /api/v1/conversations/{conversation_id}:leave`

Permissions:

- Only a request owner can edit/close/cancel it and view/decide its private applications.
- Only an applicant can withdraw their own pending application.
- Only an active `ConversationMember` can list a conversation's messages, send, or leave.
- Direct blocks are checked server-side on direct conversation creation and sending, in either direction.

Error codes and HTTP mapping:

- `SELF_APPLICATION`, `COMPANION_REQUEST_UNAVAILABLE`, `INVALID_APPLICATION_TRANSITION`, and `INVALID_COMPANION_REQUEST_TRANSITION`: `409`.
- `FORBIDDEN`: `403`.
- `APPLICATION_NOT_FOUND` and `COMPANION_REQUEST_NOT_FOUND`: `404`.
- `NOT_CONVERSATION_MEMBER` and `USER_BLOCKED`: `403`.
- `CONVERSATION_NOT_FOUND`: `404`.
- `INVALID_DIRECT_CONVERSATION` and `INVALID_BLOCK`: `409`.

## State Machines

- Request: `open -> closed | cancelled`; only owner can transition. A request accepted through an application is closed atomically.
- Application: `pending -> withdrawn | accepted | rejected`; applicant can withdraw; owner can accept/reject; terminal states are immutable.
- Conversation member: active when `left_at IS NULL`; `active -> left` through leave. Active membership is required for history and send.
- Block: active block is created idempotently; unblock deletes the existing block. Historical direct messages remain readable for current active members, but blocks prohibit new direct messages.

## Outbox and Notifications

Community writes `companion_application.created`, `.withdrawn`, `.accepted`, `.rejected`, and `companion_request.closed` events to `outbox_events` alongside aggregate changes. Chat retains `message.created` with recipient IDs. No direct write to `notifications` was added, preserving module ownership. Notification Worker mapping for newly emitted companion events is still needed.

## Migration Requirements

No Alembic revision was created, per task constraint. Current tables support the delivered functions.

Recommended follow-up migration before production expansion:

- Add a conversation-level last-message activity field or projection/index for efficient conversation sorting at scale.
- Add `last_read_at` or an `(conversation_id, user_id, last_read_message_id)` cursor-safe read marker index for efficient unread counting.
- Add `companion_applications.conversation_id` if applications must later expose their accepted group without event projection lookup.
- Add an immutable companion request metadata snapshot if destination/dates/party size/budget from the target API contract are required.

All recommendations are additive. Their downgrade should remove only the new indexes/columns after dependent reads are removed; no existing companion/chat facts need rewriting.

## Verification

- `cd backend; py -3 -m pytest tests/community tests/chat -q`
  - Passed: `10 passed`.
  - Covers application idempotency, withdrawal, owner authorization, request closure, acceptance/group-member creation, direct blocking, member-send rejection, client-message idempotency, and stable cursor pagination.
- `cd frontend-c; npm run typecheck`
  - Passed.
- `cd frontend-c; npm run test -- --run`
  - Passed: `6 files, 10 tests`.
- `cd frontend-c; npm run build`
  - Passed.
  - Existing Rollup pure-comment and chunk-size warnings remain.
- `git diff --check`
  - Passed with no whitespace errors. Repository-wide command prints pre-existing CRLF warnings for unrelated files.

## Risks and Integration Requests

- Agent B did not modify reserved `backend/app/api/router.py`. Main integrator must ensure the pre-existing community/chat routers remain included and review the newly added module routes after mounting.
- No migration was added. The existing model/table contract must already be deployed for this code to run; follow-up schema needs are listed above.
- The frontend does not yet expose a retry action for an individual failed message. It visibly keeps the `failed` state; retry can resend the same `client_message_id` safely once a UI action is added.
- The consumer UI has no explicit block/unblock controls yet; server HTTP APIs enforce the restriction.
- Group lifecycle currently supports active membership and voluntary leave. Owner-mediated group removal and invitation flows require an explicit product contract and likely a membership status/audit migration.
- Pagination uses cursor IDs tied to server-side ordered records. If a supplied cursor is deleted or belongs to another conversation, history treats it as absent and returns the first page; production may want a `INVALID_CURSOR` 400 contract.
- Notification persistence is intentionally deferred to an Outbox consumer. Main integrator should add Worker handlers for the new companion event types under the notification module's approved integration flow.
