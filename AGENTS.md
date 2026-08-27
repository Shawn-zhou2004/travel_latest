# Repository Guide

## Structure

- This is not a JavaScript workspace: `frontend-c` (consumer) and `frontend-b` (admin) are independent Vue 3/Vite projects and each needs its own `npm install` and commands run from that directory.
- `backend` is the FastAPI modular monolith. The current implementation only exposes `GET /` and `GET /api/v1/health`; the rest of `docs/API设计.md` is a target contract, not implemented behavior.
- `docker-compose.yml` runs only local infrastructure (MySQL, Redis, RabbitMQ, Elasticsearch, Nginx). Develop the API and both frontends as separate local processes.

## Local Workflow

- Copy `.env.example` to the repository-root `.env`, then start infrastructure with `docker compose up -d`. The backend settings file is resolved as `../.env`, so run backend commands from `backend`.
- From `backend`: create and activate a Python 3.11+ virtual environment, run `pip install -e .`, then `alembic upgrade head` before starting `uvicorn app.main:app --reload --port 8000`.
- Verify a database change with `alembic upgrade head`, then `alembic downgrade -1 && alembic upgrade head`. The migration uses MySQL-specific constraints, so it requires the Compose MySQL service.
- From either frontend directory: use `npm run typecheck` for focused TypeScript verification and `npm run build` for the production build. Start C with `npm run dev`; start B with `npm run dev -- --port 5174` to avoid C's default Vite port.
- Check the running API with `curl http://localhost:8000/api/v1/health`. Nginx listens on `${NGINX_PORT:-8080}` and proxies only `/api/` to the host API.

## Backend Data Changes

- SQLAlchemy models live in `backend/app/models/`; migration metadata is populated by explicit model imports in `backend/alembic/env.py`. Import a new model module there before generating or applying a migration.
- Keep schema changes in Alembic revisions under `backend/alembic/versions/`; do not rely on model edits alone to update an existing database.

## Backend Skills

### FastAPI: `fastapi`

- Trigger when writing or changing FastAPI routes, Pydantic request/response schemas, dependency injection, SSE, API exception handling, or backend HTTP authentication.
- Do not load for database-only migrations, infrastructure-only configuration, frontend-only work, or non-HTTP domain logic.
- Follow router-level prefixes/dependencies, `Annotated[..., Depends(...)]` reusable dependency aliases, explicit public response schemas, and persisted async-job state before emitting SSE progress.

### Database Migrations: `database-migration`

- Trigger when changing SQLAlchemy models, Alembic revisions, MySQL tables, indexes, foreign keys, constraints, data backfills, or rollback behavior.
- Do not load for read-only queries, Redis/Elasticsearch/RabbitMQ-only changes, or frontend-only work.
- Pair each schema change with an Alembic revision and verify it using `alembic upgrade head`, `alembic downgrade -1`, and `alembic upgrade head` against MySQL.
- Prefer additive, backward-compatible schema evolution; do not edit an applied migration in place or modify another module's private tables without an approved contract change.

## Skill Policy

### Default

- Without a direct match, do not load a skill. Backend, database, API, test, migration, and routine repository tasks must not load frontend/UI skills.
- Do not load a skill merely because its general subject is related. Load its full workflow only when the requested outcome matches the trigger below.

### Frontend Design: `frontend-design`

- Trigger when creating a new frontend UI or substantially reshaping an existing page, component, prototype, or interactive experience, including consumer-side page work governed by `docs/c端页面重构.md`.
- Ground the design in the product's subject, audience, and single job. Derive the palette, typography, layout, and one memorable signature element from that context rather than from generic dashboard or landing-page defaults.
- Before implementation, make a compact design plan covering named colors, type roles, layout structure, and the signature element. Review the plan for templated choices and revise it before writing code.
- Make deliberate typography choices with a display face, body face, and utility face when needed. Use hierarchy, weight, width, and spacing intentionally instead of relying on default type settings.
- Use structural devices such as numbering, labels, dividers, and eyebrows only when they communicate real content relationships. Remove decoration that does not serve the brief.
- Use motion selectively where it clarifies state or expresses the product. Respect reduced-motion preferences and keep the rest of the interface disciplined around one primary visual risk.
- Treat copy as part of the design: use plain, active, consistent labels; keep action names stable across flows; make errors specific and actionable; and make empty states guide the next action.
- Deliver responsive layouts down to mobile with visible keyboard focus and no overlapping or clipped content. When possible, inspect a rendered result or screenshot and critique the visual output before finishing.
- Do not default to the recurring AI-generated looks of warm cream with serif and terracotta, near-black with a single acid accent, or dense broadsheet rules unless the brief genuinely calls for them.

### Vue Development: `vue`

- Trigger when writing or changing Vue SFCs, Composition API state, `<script setup lang="ts">`, Vue macros, watchers, lifecycle hooks, or built-in Vue components.
- Do not load for CSS-only visual polish, general frontend design decisions, or non-Vue files.
- Follow the skill's Vue 3 Composition API and TypeScript guidance.

### C-End Page Refactor: `frontend-design`

- This policy applies only when the user explicitly references `docs/c端页面重构.md` or requests a consumer-side (`frontend-c`) page refactor under that document.
- Treat `docs/c端页面重构.md` as the highest-priority visual and engineering specification. Load only `frontend-design` for design guidance and `vue` when changing Vue SFC behavior or Composition API code.
- Do not load or use `design-taste-frontend`, `design-taste-frontend-v1`, `impeccable`, `gpt-taste`, `high-end-visual-design`, `redesign-existing-projects`, `minimalist-ui`, `industrial-brutalist-ui`, `image-to-code`, `imagegen-frontend-web`, `imagegen-frontend-mobile`, `brandkit`, `stitch-design-taste`, or `full-output-enforcement` for this workflow, even when their general descriptions match.
- Do not add React, Next.js, Tailwind, a new component library, a motion library, image-generation assets, hooks, or configuration. Reuse Vue 3 SFCs, scoped CSS, CSS variables, installed icons, and existing product copy.
- Before editing, produce the four-part page audit required by the document. Preserve API contracts, request logic, component props/emits contracts, business DOM-node order, event bindings, v-model bindings, permissions, and route behavior. Follow the document's continuous-DOM-wrapper, no-CSS-order, accessibility, motion, and regression-testing constraints exactly.
- After implementation, run `npm run typecheck`, affected component tests, and `npm run build` from `frontend-c`; use browser acceptance only when the user asks for it or the task requires screenshot or responsive verification.

### Browser Acceptance: `agent-browser`

- Trigger for a completed feature or module that needs browser interaction, screenshots, exploratory QA, accessibility checks, or browser-based regression acceptance.
- Do not use during routine implementation or for source-only review. Run browser acceptance in a bounded final pass, not after every edit.
- Before the first `agent-browser` command, load its current CLI workflow with `agent-browser skills get core`; load a specialized browser workflow only when its scope matches the task.

### Requirements Exploration: `brainstorming`

- Trigger only when the user explicitly asks to brainstorm, explore options, or use a plan-first process for a non-trivial feature.
- Do not load for routine implementation, focused bug fixes, configuration changes, or requirements that are already specific enough to implement.

### Implementation Planning: `writing-plans`

- After a non-trivial design specification has been approved by the user, load `writing-plans` before implementation.
- Use it to produce a detailed, testable implementation plan from the approved specification; do not begin implementation before that plan is available.
- The skill is installed globally from `obra/superpowers@writing-plans`; this repository intentionally does not install the rest of the Superpowers skill set.

### Skill Discovery: `find-skills`

- Trigger only when the user asks to find, compare, install, update, or remove a skill, or asks whether a specialized capability has an installable skill.
- Do not load to solve a task that the agent or an installed skill can already handle.

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->
