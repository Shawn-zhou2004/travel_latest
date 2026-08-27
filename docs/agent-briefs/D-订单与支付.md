# D 订单与支付模块 Brief

## 当前后端接口

订单模块位于 `backend/app/modules/orders/`，当前已有：

- `POST /api/v1/travel-search-jobs`：供应商搜索任务，当前默认 adapter 会明确表示供应商不可用。
- `GET /api/v1/travel-search-jobs/{job_id}` 和 `/offers`。
- `POST /api/v1/travel-orders`：需要 `Idempotency-Key`。
- `GET /api/v1/travel-orders`：用户自己的订单列表。
- `POST /api/v1/travel-orders/{order_id}/payments`：当前支付未配置时返回明确不可用。
- `POST /api/v1/travel-orders/{order_id}:query-payment`：订单 owner 或管理员读取支付事实。
- `POST /api/v1/payments/alipay/callback`：当前为未配置占位实现。

当前模型：`TravelSearchJob`、`TravelOffer`、`TravelOrder`、`PaymentRecord`、`PaymentCallbackEvent`、`RefundRecord`。状态以 `backend/app/modules/orders/models.py` 和 `docs/contracts/说明.md` 为准。

## 当前前端接口

- `frontend-c/src/features/orders/`。
- 消费端路由在 `frontend-c/src/router/index.ts`。
- 管理端订单只读 API 已实现为 `GET /api/v1/admin/travel-orders`，不要改变其状态机或手工状态修改权限。

## 不可假设

- 当前没有已接通的真实供应商、Alipay sandbox 凭据或回调验签配置。模块应先实现受控 mock/unavailable adapter；最终集成者负责新增持久化字段和迁移链。
- 前端支付成功页不是支付事实。
- 目标 API 文档的退款、详情、供应商履约接口未必已存在；新增时要在 handoff 说明实际契约与缺口。
