# 活动壳（`events`）

`events` app 现在只保留 **Event 壳**与生命周期，用于承载「重大活动」形态模块，不再提供通用活动 CRUD。

- 状态机与访问控制分离的约定不变：判定与流转真源 `events/lifecycle.py`（`draft` → `scheduled` / `active` → `ended` → `archived`），惰性流转、无定时任务；
- 壳字段：标题 / 简介 / 正文 / 组织者 / `start_at`（必填）/ `end_at`（可空）/ `status` / `visibility` / `module_key`；
- 形态模块放在 `events/modules/<key>/`：模型 `Meta.app_label = "events"`、迁移进 `events/migrations/`，新增形态**不改 `INSTALLED_APPS`**（约定见 `events/modules/__init__.py`）；
- **通用 `EventViewSet` 与 `/#/events`、`/#/m/events` 页面已于 2026-11 下线**（原「活动（限时）」模块撤销）；`/events/` 路径下只剩形态模块路由。

目前唯一形态模块是**明信片互寄**（`module_key="postcard"`）：

- 路由前缀 `/events/postcard/`；
- 接口文档：[明信片互寄 API](postcard.md)；
- 使用与运营说明：[明信片互寄指南](../guides/postcard.md)；
- 实施方案：[明信片互寄实施方案](../plans/postcard-exchange.md)。

> 术语：用户可见的「活动」指 `activities` app（众议 / 征集 / 展示 / 调研）；`events` 不再作为独立用户入口，只作为重大活动（明信片互寄）的宿主壳。相关设计记录：状态机与访问控制分离遵循 [ADR-0003](../adr/0003-no-shared-task-proposal-lifecycle-base.md)；权限命名遵循 [ADR-0005](../adr/0005-access-control-principle.md)。
