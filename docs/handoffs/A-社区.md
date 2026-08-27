# A 社区模块交接

状态：共享集成已解除；关注关系已接入，社区其余前端验收仍待完成。

## 已实现能力

- 后端服务层已增加点赞和收藏的幂等取消方法；重复取消不会产生重复事实。
- 后端服务层已增加只返回已发布帖子收藏记录的个人收藏查询。
- 后端服务层已增加私有帖子读取校验：已发布帖子可读取，非公开帖子仅作者或 `platform_admin` 可读取。
- 后端服务层已增加已发布帖子可见评论的分页查询。
- 后端 schema 已增加分页、评论、互动和举报响应模型。
- 后端 router 已开始将帖子列表改为 `{items, next_cursor}`，并增加收藏列表、私有读取、点赞/收藏取消和评论读取端点。
- 消费端社区页已开始从旧的 `/search/posts` 读取切换到模块实际注册的 `/posts`，并增加帖子详情、评论和互动控件。

## 修改文件

- `backend/app/modules/community/schemas.py`
- `backend/app/modules/community/service.py`
- `backend/app/modules/community/router.py`
- `frontend-c/src/features/community/types.ts`
- `frontend-c/src/features/community/CommunityPage.vue`
- `frontend-c/src/features/community/community.test.ts`
- `docs/handoffs/A-社区.md`

未修改受保护文件：`backend/app/api/router.py`、`backend/app/core/`、`backend/alembic/env.py`、`backend/alembic/versions/`、`frontend-c/src/services/`、`frontend-b/`、行程与订单模块。

## API、权限与错误码

局部新增或变更，尚未完成验收：

- `GET /posts` 改为分页响应 `{items, next_cursor}`，匿名仅返回 `published`。
- `GET /posts/me/favorites`：消费者读取自己的、仍处于 `published` 的收藏。
- `GET /posts/{post_id}/private`：已认证作者或 `platform_admin` 读取私有帖子；其他读取返回 `POST_NOT_FOUND`，避免泄露私有状态。
- `GET /posts/{post_id}/comments`：匿名仅读取已发布帖子的 `visible` 评论。
- `DELETE /posts/{post_id}/reactions/like`、`DELETE /posts/{post_id}/favorites`：消费者幂等取消，成功 `204`。
- `POST /posts/{post_id}/reports` 开始返回持久化的 `pending` 举报状态，而不是仅返回伪成功 ID。
- 新增/使用错误码：`INVALID_CURSOR`、`UNSUPPORTED_REACTION`、已有的 `POST_NOT_FOUND`、`COMMENT_NOT_FOUND`、`FORBIDDEN`、`INVALID_REPORT_TARGET`。

## 阻塞冲突

已阅读 `docs/agent-briefs/说明.md`、`docs/agent-briefs/A-社区.md`、`docs/contracts/说明.md`、`docs/数据库设计.md`、`docs/API设计.md` 和 `docs/模块集成验收清单.md`。

当前模块 brief 明确说明当前没有用户关注模型或个人收藏列表接口。目标契约要求 `POST/DELETE /users/{user_id}/follows`，但任务禁止创建 Alembic migration，且 `backend` 中不存在 `follows` 表或 ORM 模型。将关注关系放进其他社区表、内存或前端状态会违反 MySQL 事实源要求，因此已停止实现关注/取消关注。

另有接口兼容风险：当前已注册 `GET /posts` 返回数组，目标契约要求分页对象。此交接中的 router 局部改动开始切换到分页对象，但共享消费端或其他调用方是否依赖数组尚未确认，主智能体应审查后决定最终协议与兼容策略。

## 所需迁移方案

由主智能体统一创建 Alembic revision：

- 新建 `follows`：`id VARCHAR(36) PK`、`follower_id VARCHAR(36) FK users.id`、`followee_id VARCHAR(36) FK users.id`、`created_at DATETIME(6)`、`updated_at DATETIME(6)`。
- 约束：`UNIQUE(follower_id, followee_id)`、`CHECK(follower_id <> followee_id)`。
- 索引：`ix_follows_follower_id`、`ix_follows_followee_id`。
- 新增社区 `Follow` ORM 模型、关注/取消服务方法和路由。重复关注与重复取消均需幂等。
- 如最终确认分页协议，审查所有 `GET /posts` 调用方并更新功能级 API 类型，不能修改受保护共享 API client。

## 集成记录（2026-08-04）

- 已新增 `Follow` ORM 模型，并在 `20260804_0009_follows_and_providers` 中创建 MySQL `follows` 表、双向索引、唯一约束和禁止自关注约束。
- 已注册 `POST /api/v1/users/{user_id}/follows` 与 `DELETE /api/v1/users/{user_id}/follows`。重复关注和重复取消均幂等；自关注返回 `SELF_FOLLOW`，不存在的被关注用户返回 `USER_NOT_FOUND`。
- 已补充服务测试，关注、取消和自关注拒绝均已通过 SQLite 聚焦测试。
- Compose MySQL 未启动，因此 Alembic 的 upgrade/downgrade/upgrade 环境验证仍待执行。

## 测试与构建结果

- 未运行 pytest：停止时测试文件仍被其他智能体并行修改，新增社区验收用例未安全应用。
- 未运行 `frontend-c npm run typecheck`、`npm run test -- --run`、`npm run build`。
- 已运行 `git diff --check`：未报告 whitespace error；工作树内其他模块文件输出 CRLF warning。

## 风险与主智能体集成项

- 当前局部改动处于未验收状态，不应直接合并。
- `CommunityPage.vue` 的详情对话框和互动调用需要类型检查后再决定保留或拆为功能级 API 文件和独立详情页。
- 按模块 brief，应新增 `frontend-c/src/features/community/api.ts` 承载 `/posts` 的请求与类型，避免继续在页面内直接调用共享 Axios client；本次未完成该重构。
- 评论回复服务层已有同帖和 `visible` 父评论校验，仍需补充 pytest 覆盖。
- 举报状态仅表示服务端创建了 `pending` 事实，不代表审核或隐藏已完成；前端不得把举报当作内容已处理。
