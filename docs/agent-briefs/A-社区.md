# A 社区模块 Brief

## 当前后端接口

当前模块位于 `backend/app/modules/community/`，已注册的路由包括：

- `GET /api/v1/posts`：匿名读取已发布帖子。
- `GET /api/v1/posts/{post_id}`：匿名读取已发布帖子。
- `POST /api/v1/posts`：消费者创建草稿。
- `POST /api/v1/posts/{post_id}:submit`：作者提交审核。
- `POST /api/v1/posts/{post_id}:publish`：作者发布已审核帖子。
- `POST /api/v1/posts/{post_id}/reactions`：消费者点赞，当前服务端已具备幂等行为。
- `POST /api/v1/posts/{post_id}/favorites`：消费者收藏，当前服务端已具备幂等行为。
- `POST /api/v1/posts/{post_id}/comments`：消费者评论。
- `POST /api/v1/posts/{post_id}/reports`：消费者举报。
- `POST /api/v1/moderation/posts/{post_id}:publish|hide`：管理员审核动作。

当前模型：`Post`、`Comment`、`PostReaction`、`PostFavorite`、`ContentReport`，状态以 `backend/app/modules/community/models.py` 为准。

## 当前前端接口

- 页面和组件：`frontend-c/src/features/community/`。
- 当前路由定义：`frontend-c/src/router/index.ts`。
- 调用共享 Axios client，但社区模块应创建自己的功能级 API 文件，不修改 `frontend-c/src/services/api.ts`。

## 允许扩展

- 可以新增模块内的 `api.ts`、详情页、作者视图、收藏视图和组件。
- 若新增数据库字段或表，完成 ORM、服务、路由和测试，并提供迁移需求说明。最终集成者负责把迁移接到单一 Alembic 链。
- 新增 API 应保持 `/posts` 或 `/users` 资源边界，并在 handoff 列出完整请求/响应和权限。

## 不可假设

- 当前没有媒体上传完成链路。
- 当前没有用户关注模型或个人收藏列表接口。
- 当前没有评论列表、评论隐藏或取消点赞/收藏接口。
- `docs/API设计.md` 中的社区目标接口不代表当前已经存在。
