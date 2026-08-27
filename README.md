# AI Travel Platform

## Local Setup

1. Copy `.env.example` to `.env` and replace placeholder credentials before starting services.
2. Start local infrastructure with `docker compose up -d`.
3. From `backend`, create a Python 3.11+ virtual environment, run `pip install -e .`, then run `alembic upgrade head`.
4. Start the API from `backend` with `uvicorn app.main:app --reload --port 8000`.
5. Start the consumer application from `frontend-c` with `npm install` then `npm run dev`.
6. Start the admin application from `frontend-b` with `npm install` then `npm run dev -- --port 5174`.

Nginx listens on `${NGINX_PORT:-8080}` and proxies `/api/` to the API running on the host at port `8000`. It also proxies `/_AMapService/` to AMap and appends `AMAP_SECURITY_JS_CODE`, so the browser never receives that private value. The Vite applications remain independent local processes.

In production, the browser uses Nginx's `/_AMapService` proxy. In local development, it uses a fixed-target FastAPI map-service proxy, so Docker is not required for JSAPI security handling. The consumer dev server still forwards `/_AMapService` to `http://127.0.0.1:8080` for production-like local testing; set `VITE_AMAP_PROXY_TARGET` when that proxy is hosted elsewhere.

`AMAP_JS_API_KEY` is the public browser-map Key. `AMAP_SECURITY_JS_CODE` is injected only by Nginx into its AMap service proxy. `AMAP_WEB_SERVICE_KEY` is exclusively for server-side AMap Web Service calls. Other third-party integration values may remain unset until their integration stage.

## AI Architecture

The approved medium-concurrency AI architecture and rollout plan are documented in `docs/AI架构决策.md`. Do not deploy Neo4j or DeepAgents before the first LangChain RAG, LangGraph, Milvus, PostgreSQL, and `bge-m3` phase is complete.

Production purchasing and deployment guidance is in `docs/生产服务器采购与部署教程.md`; the Chinese document index is in `docs/文档导航.md`.
