# Streaming Assistant MCP Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver persisted, reconnectable SSE answers from the official travel assistant, with task-local MCP web-search fallback when reviewed official knowledge has no answer.

**Architecture:** `POST :ask-stream` persists a user message and an `ai_assistant_runs` row in PostgreSQL before returning an SSE stream. The stream reports retrieval and MCP fallback phases, emits model text deltas, then persists one complete assistant message and terminal run state. A reconnect endpoint replays persisted events or the completed message. Official RAG is queried first without a user-supplied administrative code; MCP is used only for `no_results` or `clarification_required` and contributes bounded HTTPS metadata only.

**Tech Stack:** FastAPI `StreamingResponse`, asyncpg/PostgreSQL, LangChain-compatible DashScope streaming, configured Magic MCP WebSearch, Vue 3 Fetch ReadableStream, Vitest, pytest.

## Global Constraints

- Persist the assistant run and user message before emitting any SSE event.
- Do not accept user-supplied city or administrative codes for assistant questions.
- RAG official knowledge is always first; MCP fallback applies only to no-result or clarification retrieval states.
- MCP inputs and citations are limited to title, excerpt, source host, and HTTPS URL; never fetch page bodies or write MCP results to RAG/long-term knowledge.
- Every terminal run persists exactly one assistant message or a safe error state; retrying a client message ID remains idempotent.
- SSE access uses the authenticated `fetch` request, not token query strings.
- Assistant messages remain owned by the conversation user; admin APIs do not expose prompts, runs, or streamed text.

---

### Task 1: Persist Assistant Runs

**Files:**
- Modify: `backend/app/modules/ai_memory/postgres.py`
- Modify: `backend/app/modules/ai_memory/service.py`
- Test: `backend/tests/ai_memory/test_postgres.py`

- [ ] Add `ai_assistant_runs` schema owned by PostgreSQL setup with UUID ID, conversation/user/message IDs, status `queued|running|completed|failed`, source mode `official|live_web`, immutable request message ID, result assistant message ID, safe error code/message, timestamps, and a uniqueness constraint on `(conversation_id, user_id, client_message_id)`.
- [ ] Add repository methods to create/get/transition a run and list replayable run events derived from persisted run/message state.
- [ ] Test duplicate client message IDs return the same owned run and that completed runs expose their complete assistant message.

### Task 2: Stream Official RAG Then MCP Fallback

**Files:**
- Modify: `backend/app/modules/ai_memory/assistant.py`
- Modify: `backend/app/modules/ai_memory/router.py`
- Modify: `backend/app/modules/ai_memory/schemas.py`
- Test: `backend/tests/ai_memory/test_router.py`
- Test: `backend/tests/integrations/test_websearch_provider.py`

- [ ] Add `SourceBackedAssistant.answer_stream()` using DashScope OpenAI-compatible `stream=true`, parsing SSE `choices[].delta.content` into bounded text chunks.
- [ ] Add `POST /api/v1/ai/conversations/{conversation_id}:ask-stream` and `GET /api/v1/ai/assistant-runs/{run_id}/events`.
- [ ] Emit stable event IDs and names: `progress`, `delta`, `completed`, `failed`.
- [ ] Query official RAG globally first. For no-result/clarification, construct the configured `MagicMcpWebSearchProvider`, search once with limit 8, retain valid metadata, and answer from that metadata only.
- [ ] Persist one `assistant` message containing final text, citations, and `kind: source_backed|live_web|clarification`; mark run terminal before `completed` is emitted.
- [ ] Test official result avoids MCP, no-result invokes MCP, MCP failure yields a safe clarification/error event, and reconnect returns terminal state without calling model again.

### Task 3: Consumer Streaming Client

**Files:**
- Modify: `frontend-c/src/features/ai/assistantApi.ts`
- Modify: `frontend-c/src/features/ai/pages/AiAssistantPage.vue`
- Test: `frontend-c/src/features/ai/assistantApi.test.ts`
- Test: `frontend-c/src/features/ai/pages/AiAssistantPage.test.ts`

- [ ] Replace synchronous `askAiAssistant` with a fetch-based authenticated SSE parser that returns event payloads to the page.
- [ ] Add optimistic user message and a provisional assistant message; append each `delta` to the same message without waiting for completion.
- [ ] Render retrieval/network fallback status and source type; replace provisional content with the persisted completed assistant message.
- [ ] On stream failure, reconnect once to the run event endpoint; then reload conversation history as source of truth.
- [ ] Test chunk rendering, live-web phase display, completed message replacement, and reconnect behavior.

### Task 4: Verify And Document

**Files:**
- Modify: `docs/API设计.md`
- Modify: `docs/本地验收使用手册.md`
- Modify: `docs/错误复盘记录.md`

- [ ] Document streaming endpoints, event names, run persistence, official-first retrieval, and MCP metadata-only boundary.
- [ ] Run backend focused tests, consumer tests/typecheck/build, and a real local `curl` or authenticated browser check that observes `progress`, at least one `delta`, and `completed`.
