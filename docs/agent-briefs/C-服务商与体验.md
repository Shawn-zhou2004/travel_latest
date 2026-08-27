# C 供应商与体验模块 Brief

## 当前实现状态

项目当前没有 `backend/app/modules/providers/` 领域模块、供应商申请模型或体验预订模型。管理端 `GET /api/v1/admin/providers` 当前明确返回 `501 PROVIDER_REVIEW_NOT_IMPLEMENTED`，这是诚实的占位状态，不得替换为假数据。

## 现有集成边界

- 管理运营 API：`backend/app/modules/admin/router.py`。
- 管理端供应商审核 UI：`frontend-b/src/features/admin/`。
- AMap POI 验证服务：`backend/app/modules/maps/service.py`。
- 当前订单模型与状态机：`backend/app/modules/orders/`，不可直接改写。

## 期望的模块产物

- 新建 `backend/app/modules/providers/`，包含 models、schemas、service、router、tests。
- 新建消费者体验页面和管理端供应商页面；可修改路由文件仅追加本模块路由。
- 供应商申请、审核、provider scope、体验、场次、预约、核销和评价应有明确状态机、权限和 API。

## 不可假设

- 供应商申请还没有表，因此子智能体必须完成完整 ORM/字段/索引/FK/check constraint 设计；最终集成者负责迁移、路由装配和替换管理端的 `501` 委托。
- 预约不可直接当作支付成功；与 `TravelOrder` 的连接需要明确新契约。
- 体验地点必须使用已验证 AMap POI，不能接收任意地点字符串作为业务事实。
