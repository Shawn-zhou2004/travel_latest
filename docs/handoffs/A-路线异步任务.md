# 智能体 A 交接：路线异步化

状态：待主智能体审查。当前工作仅完成后端异步任务骨架的一部分；未执行数据库迁移、测试、前端类型检查或构建。不得将本交接视为可合并完成状态。

## 已完成的用户能力

- `recalculate_route` 已从请求事务中的同步高德逐段计算改为创建 `RouteCalculationJob`，并在同一事务写入 `itinerary.route_calculation_requested` Outbox 事件。
- Worker 注册了该事件的消费者。消费者调用 `ItineraryService.process_route_calculation()` 执行高德驾车路线计算。
- 任务记录提交时按 `display_order` 获取的 `ItineraryEvent.id` 序列。Worker 开始替换 `RouteSegment` 前会验证当前事件 ID 序列完全一致，因此不重排用户地点，也不允许过期任务覆盖后来变更的地点顺序。
- 计算成功后才删除并重建当天 `RouteSegment`；高德失败、无效坐标、日期被删除或任务已过期时，任务标记为 `failed` 且保留旧路线。
- 行程快照中已增加每一天的 `route_calculation`：`id`、`status`、`error_code`，用于前端显示任务状态。
- 增加授权后的任务查询端点，支持前端轮询单个任务状态。

## 修改文件清单

- `backend/app/modules/itineraries/models.py`
  - 新增 `RouteCalculationJob` ORM 模型。
- `backend/app/modules/itineraries/schemas.py`
  - 新增 `RouteCalculationJobResponse`，在 `OperationResponse` 增加可选 `route_job`。
- `backend/app/modules/itineraries/service.py`
  - 路线重算改为任务入队和 Outbox 写入。
  - 新增任务查询、Worker 路线计算、最新任务快照辅助方法。
- `backend/app/modules/itineraries/router.py`
  - 新增路线任务查询接口。
- `backend/app/workers/domain_handlers.py`
  - 注册 `itinerary.route_calculation_requested` 的 Worker handler。
- `backend/alembic/versions/20260804_0002_route_calculation_jobs.py`
  - 新增任务表迁移。
- `docs/handoffs/A-路线异步任务.md`
  - 本交接报告。

明确未修改的共享文件：

- `backend/app/api/router.py`
- `backend/app/core/settings.py`
- `backend/alembic/env.py`
- `docker-compose.yml`
- `nginx/nginx.conf`
- `frontend-c/src/services/api.ts`
- `frontend-b/src/services/api.ts`

## 新增或变更的 API、权限、错误码

- 保持既有写接口：`POST /api/v1/itineraries/{itinerary_id}:operations`，`operation_type: "recalculate_route"`。
  - 成功时返回 `APPLIED`、新版本快照和可选 `route_job`。
  - 任务状态初始为 `queued`；快照内当天的 `route_calculation` 也为 `queued`。
- 新增：`GET /api/v1/itineraries/{itinerary_id}/route-calculations/{job_id}`。
  - 仅行程 owner 或已接受协作者可读，沿用 `ItineraryService._can_read()`。
  - 不存在、任务不属于该行程或无读取权限均返回 `404`，detail code 为 `ROUTE_CALCULATION_NOT_FOUND`。
- 任务状态：`queued`、`calculating`、`completed`、`failed`。
- Worker 失败错误码：`DAY_NOT_FOUND`、`STALE_ROUTE_REQUEST`、以及地图服务产生的 `MAP_UNAVAILABLE`。
- 当前 API `OperationResponse.code` 未增加新的写操作错误码；路线计算外部错误异步写入任务 `error_code`。

## 数据模型与 Alembic Migration

- 新表：`route_calculation_jobs`。
  - 字段：`id`、`itinerary_id`、`day_id`、`requested_by`、`event_ids` JSON、`status`、`error_code`、`completed_at`、时间戳。
  - `status` 有数据库 check constraint。
  - `itinerary_id` 和 `day_id` 已建索引；关联行程和日期时 `CASCADE` 删除。
- 迁移文件：`20260804_0002_route_calculation_jobs`。
- 高风险：此迁移当前 `down_revision = "20260801_0001"`，但工作树的主迁移链已有 `20260801_0002` 至 `20260804_0006`。主智能体必须在合并时把该迁移改接到最终单一 head，或按团队策略生成 merge revision；当前状态会造成 Alembic 多 head。
- `backend/alembic/env.py` 本身已有 `app.modules.itineraries.models` 导入，因此无需为新模型修改该共享文件。

## 已运行的测试、类型检查、构建结果

- 未运行 pytest。
- 未运行 `alembic upgrade head`、`alembic downgrade -1` 或二次升级。
- 未运行 `frontend-c` 的 `npm run typecheck` 或 `npm run build`。
- 未运行浏览器验收。
- 仅运行了 `git diff --check`。结果没有 whitespace error，但输出了工作树内其他文件的 CRLF 转换 warning。

## 未完成项、已知风险、需要我对接的共享文件

- 未完成：消费端前端尚未实现 `queued`、`calculating`、`completed`、`failed` 的可见状态、轮询和完成后刷新快照。现有 `routeUpdating` 仍仅包裹 HTTP 写请求，不能表达异步任务生命周期。
- 未完成：测试需要替换旧的同步 `test_recalculate_route_persists_real_route_segments`，新增 Outbox、Worker 成功、Worker 失败保留旧分段、过期请求不覆盖排序、任务查询权限测试。
- 未完成：在 MySQL 上验证迁移升级、降级和再升级。
- 风险：`process_route_calculation()` 先将状态设置为 `calculating`，并在一次 Worker consumer 事务中完成所有网络调用。事件消费重试时事务会回滚该状态，因此对外仍会显示 `queued`，直至成功或最终进入 DLQ；若产品需要持久可观测的“计算中”状态，需要单独提交状态转换或将网络计算与写入拆成两个事务。
- 风险：Worker 仅按事件 ID 序列防止排序或地点集合过期；同一事件 ID 不变但 POI 快照坐标被未来功能修改时不会判定陈旧。目前现有操作不会编辑 POI 坐标。
- 风险：少于两个地点的任务会完成并写入空 `RouteSegment` 集合。这是保留旧路线策略的例外，且正常地点编辑已经会清理旧分段；主智能体需确认产品希望此情形标记失败还是清空旧路线。
- 需要主智能体对接的共享文件：
  - `frontend-c/src/features/itineraries/api.ts`：添加 `RouteCalculationJob` 类型与 GET 请求封装。该文件不在禁止列表。
  - `frontend-c/src/features/itineraries/stores/itinerary.ts`：管理每个 day 的任务状态、轮询、结束后的行程快照刷新。
  - `frontend-c/src/features/itineraries/pages/ItineraryWorkspacePage.vue` 和 `components/MapPanel.vue`：将按钮和地图状态文案改为排队、计算、完成、失败；失败必须说明旧路线可能仍显示。
  - 迁移链归属由主智能体统一调整；不要在本任务中改 `backend/alembic/env.py`。
  - 如需要 API 聚合确认，`backend/app/api/router.py` 为受保护共享文件，当前行程 router 已由现有聚合包含，因此本任务不应修改它。
