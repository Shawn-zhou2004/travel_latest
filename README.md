# 逐野 · AI Travel Planner

面向自由行用户的 AI 行程规划平台。用户输入目的地与偏好，系统自动完成分域检索、路线规划、POI 核验并生成逐日行程；用户确认后落库定稿，另含流式 AI 旅行问答助手。

> 一个完整的「LLM 应用工程化」参考实现：LangGraph 多节点工作流、分域 RAG、软 HITL 人机确认、可靠消息投递与多层幂等，全部落到生产级细节（乐观锁、审计、死信队列、幂等认领）。

## 核心特性

- **LangGraph 8 节点行程生成工作流**：理解需求 → 目的地解析 → 分域检索 → 官方知识检索 → 实时源搜索 → POI 核验 → 智能体规划 → 结果校验；PostgreSQL Checkpointer 持久化执行状态，节点级审计落库，全链路 trace_id 追溯。
- **受控智能体规划**：规划节点升级为 ReAct 智能体，自主调用天气、知识库、网页搜索等只读工具补齐证据；输出强制约束在已验证的 POI 候选池内，从机制上抑制幻觉。
- **三域隔离 RAG**：官方知识 / 社区内容 / 用户私人记忆分域存储（独立 Milvus collection + Elasticsearch 索引）；Milvus 向量召回 + ES BM25 关键词召回，RRF 排序输出带 citation 的 top8 上下文；私人域在检索层强制携带 `user_id` 过滤，不依赖 prompt 约束。
- **软 HITL 人在环确认流**：AI 生成不可变行程预览（只读快照），用户确认后经独立 apply 接口落库（If-Match-Version 乐观锁版本递增）；待确认任务列表 + jobId 深链恢复，异步生成中途退出页面不丢任务。
- **可靠事件投递**：Outbox 模式 + RabbitMQ Publisher Confirms 实现事件不丢不重；消费端 `(consumer_name, event_id)` 唯一约束幂等，失败重试 3 次后进死信队列。
- **任务幂等认领**：MySQL 行锁（FOR UPDATE）认领生成任务，仅 `queued` 状态可执行；进度校验 trace_id 且阶段只进不退，防止旧的延迟投递覆盖新进度。
- **结构化输出自纠错**：通义千问结构化 JSON 输出 + 校验失败自动重试；每个景点经高德 API 验证存在性与城市码，确保落脚点真实。
- **流式 AI 旅行助手**：ReAct 智能体挂载 7 个只读工具，`astream_events` 实现 SSE 流式输出；`client_message_id` 唯一索引幂等，杜绝重复扣费。
- **双粒度计费与会员权益**：助手按消息级、行程生成按任务级扣费；会员购买立即生效、已有排队周期自动顺延；额度扣减用行锁防超扣。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.0 (async) / Alembic |
| AI 编排 | LangGraph / LangChain / PostgreSQL Checkpointer |
| 检索 | Milvus（向量）+ Elasticsearch 8（BM25）+ RRF 融合 |
| 存储 | MySQL 8（业务库）+ PostgreSQL（AI 状态/记忆）+ Redis + S3 兼容对象存储（MinIO） |
| 消息 | RabbitMQ（Outbox / Publisher Confirms / 重试 / 死信） |
| 前端 | Vue 3 + Vite + TypeScript + Pinia（消费端 `frontend-c` / 管理端 `frontend-b`） |
| 网关 | Nginx（反向代理 + 高德安全代理） |
| LLM | 通义千问（DashScope OpenAI 兼容协议） |

## 仓库结构

```
backend/           FastAPI 模块化单体（app/modules 按领域拆分，tests 单测覆盖）
frontend-c/        消费端 Vue 3 应用（行程规划、社区、订单、会员、AI 助手）
frontend-b/        管理端 Vue 3 应用（用户、AI 运营、知识治理）
docs/              设计与工程文档（见下方导航）
docker-compose.yml 本地基础设施：MySQL / Redis / RabbitMQ / Elasticsearch / Nginx
```

### 文档导航

| 目录 | 内容 |
|---|---|
| `docs/AI旅行平台需求文档.md` / `docs/API设计.md` | 需求与 API 契约 |
| `docs/项目分包结构与业务职责详解.md` | 模块划分与各域职责 |
| `docs/superpowers/specs/`（14 份） | 关键特性设计文档：分域 RAG、受控多智能体、智能行程规划、会员支付、支付宝二维码、群聊实时消息、显式 AI 记忆等 |
| `docs/superpowers/plans/`（25 份） | 与设计文档一一对应的实施计划与验收清单 |
| `docs/contracts/` | 权限矩阵、领域事件契约 |
| `docs/handoffs/` | 各业务域模块交接说明与主智能体集成报告 |
| `docs/agent-briefs/` | 各业务域智能体任务简报 |

## 快速开始

### 1. 环境要求

- Docker + Docker Compose
- Python 3.11+
- Node.js 18+

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少修改数据库默认密码与 `JWT_SECRET`。管理员账号由 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 配置，启动时自动同步。

不配置任何 AI 相关 Key 时平台仍可启动（`AI_ENABLED=false`），AI 能力整块关闭。

### 3. 启动本地基础设施

```bash
docker compose up -d
```

包含 MySQL 8.4、Redis 7.4、RabbitMQ 4（含队列定义）、Elasticsearch 8.15、Nginx。Milvus / PostgreSQL / 对象存储需自备实例，未配置不影响非 AI 功能。

### 4. 启动后端

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows；Linux/macOS 用 source .venv/bin/activate
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

> 后端 settings 按相对路径 `../.env` 解析，务必在 `backend` 目录下执行命令。

### 5. 启动前端

```bash
# 消费端（默认 5173）
cd frontend-c && npm install && npm run dev

# 管理端（换端口避免冲突）
cd frontend-b && npm install && npm run dev -- --port 5174
```

### 6. 验证

```bash
curl http://localhost:8000/api/v1/health
```

Nginx 监听 `${NGINX_PORT:-8080}`，将 `/api/` 代理到宿主机 8000 端口的 API，并把 `/_AMapService/` 代理到高德同时注入安全码——浏览器永远拿不到 `AMAP_SECURITY_JS_CODE` 私有值。

## AI 能力配置

启用 AI 行程规划与助手需要以下外部服务：

| 变量 | 用途 |
|---|---|
| `DASHSCOPE_API_KEY` | 通义千问 LLM（规划/助手/结构化输出） |
| `AI_ENABLED` | 设为 `true` 开启 AI 能力 |
| `AI_POSTGRES_DSN` | LangGraph Checkpointer + AI 记忆存储 |
| `MILVUS_URI` / `MILVUS_TOKEN` | 向量检索 |
| `EMBEDDING_*` | Embedding 服务（bge-m3 兼容接口） |
| `AMAP_JS_API_KEY` / `AMAP_SECURITY_JS_CODE` / `AMAP_WEB_SERVICE_KEY` | 高德地图与 POI 核验 |

## 运行测试

```bash
cd backend
pip install -e ".[test]"
pytest
```

前端在对应目录执行 `npm run typecheck` 与 `npm run build`。

## License

[MIT](LICENSE)
