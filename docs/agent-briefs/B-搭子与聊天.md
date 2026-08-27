# B 结伴与聊天模块 Brief

## 当前后端接口

结伴路由由 `backend/app/modules/community/router.py` 提供：

- `GET /api/v1/companion-requests`：匿名读取公开且已审核通过的请求。
- `POST /api/v1/companion-requests`：消费者创建请求。
- `POST /api/v1/companion-requests/{request_id}/applications`：消费者申请。
- `POST /api/v1/companion-applications/{application_id}:accept|reject`：请求 owner 决定申请。

聊天路由由 `backend/app/modules/chat/` 提供。开始实现前必须阅读其 router、service、schemas 和 websocket 文件，而不是仅依据目标契约推断。

当前结伴模型：`CompanionRequest`、`CompanionApplication`。当前聊天模型在 `backend/app/modules/chat/models.py`。结伴请求公开条件包含业务 `status == open` 与运营 `review_status == approved`。

## 当前前端接口

- 结伴页面：`frontend-c/src/features/community/CompanionsPage.vue`。
- 聊天页面/组件：`frontend-c/src/features/chat/`。
- 消费端路由：`frontend-c/src/router/index.ts`。

## 允许扩展

- 在 community/chat 模块内部新增 API、服务、页面和测试。
- 新的消息写入必须保持 `client_message_id` 幂等语义，若当前协议使用不同名称，先以源码为准。
- 新通知只能通过 Outbox 与 notifications 模块交互。

## 不可假设

- 当前没有完整申请列表、撤回、请求关闭或群成员管理 UI。
- WebSocket 不是消息事实来源；HTTP 历史读取、权限和重连恢复必须独立成立。
- `docs/API设计.md` 中的 cursor 分页是目标要求，现有路由可能尚未实现。
