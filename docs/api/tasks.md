# 任务 API

成员发起、可指派负责人与协作者的工作项（任务）的增删改查、认领审批、状态流转、指派与标签管理。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0002 统一附件端点 + 抽象权限规则](../adr/0002-unified-attachment-endpoint-and-permission.md)、[ADR-0003 不抽取任务 / 申报共享生命周期基类](../adr/0003-no-shared-task-proposal-lifecycle-base.md)、[ADR-0006 账号认证模型](../adr/0006-verification-model.md)、[ADR-0012 附件创建接缝](../adr/0012-attachment-create-seam.md)

挂载前缀 `/tasks/`，路由由 DRF `DefaultRouter` 生成：任务集合在 `/tasks/tasks/`，标签集合在 `/tasks/tags/`。状态机与权限判定集中在 `tasks/lifecycle.py`，视图层只是薄适配（认领、审批、完成、指派等动作名与 `available_actions` 中的取值一一对应）。任务是统一附件的父级之一，附件上传 / 删除走 `/attachments/`，本模块详情只读回显。

## 状态机速查

`Task.status` 取值：`pending`（待处理，无负责人）、`review`（认领审核中——已有待审认领申请；模型标签「审核中」）、`in_progress`（进行中，已设负责人）、`reviewing`（待验收）、`completed`（已完成）、`cancelled`（已取消）。

主链路：`pending` —claim→ `review` —approve_claim→ `in_progress` —complete→ `reviewing` —approve_completion→ `completed`；`reject_completion` 把 `reviewing` 打回 `in_progress`；`cancel` 把非终态（`pending` / `in_progress` / `reviewing` / `review`）置 `cancelled`；创建与 `assign` 都按「有无负责人」联动 `pending` / `in_progress`（`status_for_assignee`）。

| 动作 | 源状态 | 允许谁 | 效果 |
|---|---|---|---|
| `claim` | `pending` / `review` | 非创建者且任务无负责人 | 新建认领申请；首个申请把任务转 `review` |
| `approve_claim` | `review` | 创建者 或 `tasks.manage_tasks` | 申请置 `approved`，申请人成为负责人，任务 `in_progress` |
| `reject_claim` | `review` | 创建者 或 `tasks.manage_tasks` | 申请置 `rejected`；无其它待审申请时任务回 `pending` |
| `complete` | `in_progress` | 活跃参与者（负责人 / 协作者）或 `tasks.manage_tasks` | 任务 `reviewing`，清空 `reject_reason` |
| `approve_completion` | `reviewing` | 创建者 或 `tasks.manage_tasks` | 任务 `completed`，写 `completed_at` |
| `reject_completion` | `reviewing` | 创建者 或 `tasks.manage_tasks`，必填理由 | 任务 `in_progress`，写 `reject_reason` |
| `cancel` | 上述四种非终态 | 创建者 或 `tasks.manage_tasks` | 任务 `cancelled` |
| `assign` | 任意 | `tasks.assign_task` | 设 / 清负责人并联动状态 |

优先级 `priority`：`low` / `medium` / `high` / `urgent`（默认 `medium`）。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | `/tasks/tasks/` | 登录 | — | 任务列表（分页 20/页；`?all=1` 全量裸数组）|
| POST | `/tasks/tasks/` | 已认证 | — | 创建任务（自动建评论区）|
| GET | `/tasks/tasks/{id}/` | 登录 | — | 任务详情（含 `available_actions`）|
| PUT / PATCH | `/tasks/tasks/{id}/` | 已认证 | 仅 `pending`；创建者或 `tasks.manage_tasks` | 编辑任务 |
| DELETE | `/tasks/tasks/{id}/` | 已认证 | 仅 `pending`；创建者或 `tasks.manage_tasks` | 删除任务 |
| POST | `/tasks/tasks/{id}/claim/` | 已认证 | — | 申请认领 |
| POST | `/tasks/tasks/{id}/approve_claim/` | 登录 | 创建者或 `tasks.manage_tasks` | 批准认领申请 |
| POST | `/tasks/tasks/{id}/reject_claim/` | 登录 | 创建者或 `tasks.manage_tasks` | 拒绝认领申请 |
| POST | `/tasks/tasks/{id}/complete/` | 已认证 | 活跃参与者或 `tasks.manage_tasks` | 提交验收 |
| POST | `/tasks/tasks/{id}/approve_completion/` | 登录 | 创建者或 `tasks.manage_tasks` | 通过验收 |
| POST | `/tasks/tasks/{id}/reject_completion/` | 登录 | 创建者或 `tasks.manage_tasks` | 打回（必填理由）|
| POST | `/tasks/tasks/{id}/cancel/` | 已认证 | 创建者或 `tasks.manage_tasks` | 取消任务 |
| POST | `/tasks/tasks/{id}/assign/` | 登录 | `tasks.assign_task` | 指派 / 清空负责人 |
| GET | `/tasks/tasks/my_tasks/` | 登录 | — | 我的任务（分页）|
| GET | `/tasks/tags/` | 登录 | — | 标签全量裸数组（不分页）|
| POST | `/tasks/tags/` | 登录 | `common.manage_tags` | 新建标签 |
| GET | `/tasks/tags/{id}/` | 登录 | — | 标签详情 |
| PUT / PATCH | `/tasks/tags/{id}/` | 登录 | `common.manage_tags` | 编辑标签 |
| DELETE | `/tasks/tags/{id}/` | 登录 | `common.manage_tags` | 删除标签 |
| GET | `/tasks/` | 登录 | — | DRF 路由根（索引，自动生成）|

「已认证」指 `IsVerified`（任一认证通道 approved，ADR-0006）；`tasks.manage_tasks` / `common.manage_tags` / `tasks.assign_task` 是模型权限代号，社长默认组持有。标签模型 2026-10 移入 `common`（表名 `tasks_tag` 与 `/tasks/tags/` 路径不变，权限代号变 `common.manage_tags`；既有授权已随迁移复制）。

列表 / 详情中的用户引用统一为 `{id, username, nickname, avatar}`；仅当查看者即本人时额外带 `email`。时间字段为 UTC ISO 8601（如 `2026-09-19T04:30:00Z`）。

## 端点详情

### 任务列表
`GET /tasks/tasks/`

**认证**：登录；**权限**：—（所有登录用户可见全部任务）

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| page | int | 否 | 页码（20/页），越界返回 404 |
| all | string | 否 | `"1"` 时返回全量裸数组（时间线 / 甘特图用），筛选仍然生效 |
| status | string | 否 | `pending` / `in_progress` / `reviewing` / `review` / `completed` / `cancelled` |
| priority | string | 否 | `low` / `medium` / `high` / `urgent` |
| assignee | int | 否 | 负责人用户 id |
| creator | int | 否 | 创建人用户 id |
| search | string | 否 | 在 `title`、`description` 中搜索 |
| ordering | string | 否 | `created_at` / `completed_at` / `priority` / `status`，前缀 `-` 降序；默认 `-created_at` |

**响应 `200 OK`**（默认分页信封）

```json
{
  "count": 25,
  "next": "http://localhost:8000/tasks/tasks/?page=2",
  "previous": null,
  "results": [
    {
      "id": 12,
      "title": "招新宣传片剪辑",
      "status": "in_progress",
      "priority": "high",
      "creator": { "id": 3, "username": "zhang", "nickname": "张同学", "avatar": null },
      "assignee": { "id": 7, "username": "li", "nickname": "李同学", "avatar": "/media/avatars/li.png" },
      "tags": [{ "id": 2, "name": "视频", "color": "#007bff", "task_count": 4 }],
      "completed_at": null,
      "reject_reason": "",
      "attachment_count": 2,
      "created_at": "2026-09-18T09:12:03Z",
      "updated_at": "2026-09-19T04:30:11Z"
    }
  ]
}
```

`?all=1` 时响应体为同一序列化器的裸数组（无 `count` / `next` / `previous`）。列表序列化器不含 `description` 与 `available_actions`。错误：未登录 → 401 / 403；`page` 越界 → 404。

### 创建任务
`POST /tasks/tasks/`

**认证**：已认证（`IsVerified`）；**权限**：—（所有登录且已认证的用户可建任务）

**请求体**（`title` 必填；`assignee_id` 设了就建为 `in_progress`，否则 `pending`；`tag_ids` / `collaborator_ids` 为 id 数组；`comment_thread_status` 为 `open` / `muted` / `closed`，创建时顺带设评论区状态，无协管权限 → 403）

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| title | string | 是 | 标题，≤200 字 |
| description | string | 否 | 描述，可为空 |
| priority | string | 否 | 默认 `medium` |
| assignee_id | int \| null | 否 | 负责人用户 id |
| tag_ids | int[] | 否 | 标签 id 列表 |
| collaborator_ids | int[] | 否 | 协作者用户 id 列表 |
| comment_thread_status | string | 否 | 创建时顺带设评论区状态 |

**响应 `201 Created`**：任务详情（见「任务详情」字段表），`status` 由负责人联动决定。`creator` 取自登录用户，任务创建时同步建一条默认开放的评论区（`thread_for`）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 字段校验失败（如 `title` 缺失、`tag_ids` 含不存在的标签）|
| 403 | 未认证（`IsVerified`）或试图设置无权限的 `comment_thread_status` |

### 任务详情
`GET /tasks/tasks/{id}/`

**认证**：登录；**权限**：—

**响应 `200 OK`**（此例为负责人视角）

```json
{
  "id": 12,
  "title": "招新宣传片剪辑",
  "description": "剪 90 秒短片，素材见附件。",
  "status": "in_progress",
  "priority": "high",
  "creator": { "id": 3, "username": "zhang", "nickname": "张同学", "avatar": null },
  "assignee": { "id": 7, "username": "li", "nickname": "李同学", "avatar": "/media/avatars/li.png" },
  "collaborators": [{ "id": 9, "username": "wang", "nickname": "王同学", "avatar": null }],
  "tags": [{ "id": 2, "name": "视频", "color": "#007bff", "task_count": 4 }],
  "attachments": [
    {
      "id": 88,
      "file_url": "http://localhost:8000/media/attachments/6f1c9a2e.mp4",
      "file_type": "video",
      "file_name": "招新粗剪.mp4",
      "file_size": 52428800,
      "uploaded_by": { "id": 7, "username": "li", "nickname": "李同学", "avatar": null },
      "uploaded_at": "2026-09-18T10:00:00Z"
    }
  ],
  "claim_requests": [
    {
      "id": 31,
      "task": 12,
      "claimant": { "id": 7, "username": "li", "nickname": "李同学", "avatar": null },
      "status": "approved",
      "reason": "我熟悉剪辑",
      "reviewed_by": { "id": 3, "username": "zhang", "nickname": "张同学", "avatar": null },
      "reviewed_at": "2026-09-18T11:00:00Z",
      "created_at": "2026-09-18T10:40:00Z"
    }
  ],
  "available_actions": ["complete"],
  "comment_thread": { "id": 57, "status": "open", "can_manage": false },
  "completed_at": null,
  "reject_reason": "",
  "created_at": "2026-09-18T09:12:03Z",
  "updated_at": "2026-09-19T04:30:11Z"
}
```

字段与类型：`title` / `description` 字符串；`status` / `priority` 枚举（见上）；`creator` / `assignee` 用户引用或 `null`；`collaborators` 用户引用数组；`tags` 标签数组；`attachments` 附件数组；`claim_requests` 认领申请数组（按 `-created_at`，含已处理）；`available_actions` 当前查看者可执行的动作名数组（有序：`claim, approve_claim, reject_claim, complete, approve_completion, reject_completion, cancel, assign`；未登录为空；仅详情带此字段）；`comment_thread` = `{id, status, can_manage}`；`completed_at` / `reject_reason` 为完成时间与最近一次打回理由。

**错误**：未登录 → 401 / 403；不存在 → 404。

### 编辑任务
`PUT / PATCH /tasks/tasks/{id}/`

**认证**：已认证；**权限**：任务须为 `pending`，且查看者是创建者或持 `tasks.manage_tasks`（进入认领 / 进行后对所有人锁定，含管理权限者）

**请求体**：同创建（`title` / `description` / `priority` / `assignee_id` / `tag_ids` / `collaborator_ids` / `comment_thread_status`）；`tag_ids`、`collaborator_ids` 为**整体替换**，传空数组即清空。`creator` / `status` / `completed_at` / `reject_reason` / `created_at` / `updated_at` 只读。

**响应 `200 OK`**：任务详情。

**错误**：400 字段校验失败；403 非 `pending` 状态、非创建者且无 `tasks.manage_tasks`、或未认证；404 任务不存在。

### 删除任务
`DELETE /tasks/tasks/{id}/`

**认证**：已认证；**权限**：同编辑（仅 `pending`，创建者或 `tasks.manage_tasks`）

**响应 `204 No Content`**：无正文。连带删除附件行（磁盘文件由 attachments 信号回收）与其评论区（CASCADE）。

**错误**：403 非 `pending` / 无权 / 未认证；404 不存在。

### 申请认领
`POST /tasks/tasks/{id}/claim/`

**认证**：已认证；**权限**：—（服务端判定：非创建者且任务无负责人）

**请求体**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| reason | string | 否 | 申请理由，可空 |

**响应 `201 Created`**：新建的认领申请（不是任务详情）

```json
{
  "id": 31,
  "task": 12,
  "claimant": { "id": 9, "username": "wang", "nickname": "王同学", "avatar": null },
  "status": "pending",
  "reason": "我熟悉剪辑",
  "reviewed_by": null,
  "reviewed_at": null,
  "created_at": "2026-09-18T10:40:00Z"
}
```

首个申请把任务从 `pending` 流转到 `review`（认领审核）；同一人对同一任务每任务仅一条申请（unique_together）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 状态不允许（不在 `pending` / `review`）→ `当前无法申请认领`；重复申请 → `你已经申请过认领此任务` |
| 403 | 创建者申请、任务已有负责人 → `当前无法申请认领`；未认证 |
| 404 | 任务不存在 |

### 批准认领申请
`POST /tasks/tasks/{id}/approve_claim/`

**认证**：登录；**权限**：创建者或 `tasks.manage_tasks`（动作在 `review` 状态）

**请求体**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| claim_id | int | 是 | 待审认领申请 id（须属于该任务且 `status=pending`）|

**响应 `200 OK`**：任务详情；申请人成为 `assignee`，任务转 `in_progress`，申请记 `reviewed_by` / `reviewed_at`。

**错误**：400 状态非 `review` → `当前无法审批认领`；403 无权 → `当前无法审批认领`；404 `认领请求不存在或已处理` / 任务不存在。

### 拒绝认领申请
`POST /tasks/tasks/{id}/reject_claim/`

**认证**：登录；**权限**：创建者或 `tasks.manage_tasks`

**请求体**：`claim_id`（int，必填）

**响应 `200 OK`**：任务详情；申请置 `rejected`；若已无其它待审申请，任务从 `review` 回退 `pending`。

**错误**：同「批准认领申请」。

### 提交验收
`POST /tasks/tasks/{id}/complete/`

**认证**：已认证；**权限**：活跃参与者（`in_progress` 时的负责人或协作者）或 `tasks.manage_tasks`（要求任务处于 `in_progress`）

**请求体**：无。

**响应 `200 OK`**：任务详情；任务转 `reviewing`，`reject_reason` 清空。

**错误**：400 状态不允许 → `当前无法提交验收`；403 非参与者且无管理权限 → `当前无法提交验收`，未认证 → `请先完成账号认证后再使用此功能（发帖 / 发消息 / 建申报等）。`；404 任务不存在。

### 通过验收
`POST /tasks/tasks/{id}/approve_completion/`

**认证**：登录；**权限**：创建者或 `tasks.manage_tasks`（要求任务处于 `reviewing`）

**请求体**：无。

**响应 `200 OK`**：任务详情；任务转 `completed` 并写 `completed_at`。

**错误**：400 / 403 → `当前无法通过验收`；404 任务不存在。

### 打回验收
`POST /tasks/tasks/{id}/reject_completion/`

**认证**：登录；**权限**：创建者或 `tasks.manage_tasks`（要求任务处于 `reviewing`）

**请求体**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| reason | string | 是 | 打回理由（去空白后非空）|

**响应 `200 OK`**：任务详情；任务回 `in_progress`，`reject_reason` 记打回理由；负责人不变。

**错误**：400 状态不允许 → `当前无法打回验收`，缺理由 → `请填写打回理由`；403 无权 → `当前无法打回验收`；404 任务不存在。

### 取消任务
`POST /tasks/tasks/{id}/cancel/`

**认证**：已认证；**权限**：创建者或 `tasks.manage_tasks`（要求任务处于非终态：`pending` / `in_progress` / `reviewing` / `review`）

**请求体**：无。

**响应 `200 OK`**：任务详情；任务转 `cancelled`（不记录取消人 / 取消时间）。

**错误**：400 / 403 → `当前无法取消任务`；404 任务不存在。

### 指派负责人
`POST /tasks/tasks/{id}/assign/`

**认证**：登录；**权限**：`tasks.assign_task`

**请求体**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| assignee_id | int \| null | 否 | 目标用户 id；缺省或 `null` 表示**清空负责人** |

**响应 `200 OK`**：任务详情；设了负责人则状态 `in_progress`，清空则回到 `pending`（不校验目标是否已认证）。

**错误**：403 `无指派权限`；404 目标用户不存在 → `用户不存在`；404 任务不存在。

### 我的任务
`GET /tasks/tasks/my_tasks/`

**认证**：登录；**权限**：—

**查询参数**：与任务列表相同的 `status` / `priority` / `assignee` / `creator` / `search` / `ordering` / `page`（不支持 `?all=1`）。

**响应 `200 OK`**：分页信封，条目为列表序列化器；范围是「我创建的 OR 我负责的 OR 我是协作者的」任务的并集（去重）。

**错误**：未登录 → 401 / 403。

### 标签列表
`GET /tasks/tags/`

**认证**：登录；**权限**：—

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| search | string | 否 | 按 `name` 过滤 |

**响应 `200 OK`**：裸数组（该 ViewSet 关闭分页，供表单一次性拉全量），按 `name` 升序。

```json
[
  { "id": 2, "name": "视频", "color": "#007bff", "task_count": 4 },
  { "id": 5, "name": "排版", "color": "#28a745", "task_count": 0 }
]
```

### 新建标签
`POST /tasks/tags/`

**认证**：登录；**权限**：`common.manage_tags`

**请求体**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| name | string | 是 | 唯一，≤50 字 |
| color | string | 否 | 颜色值，≤7 字符，默认 `#007bff` |

**响应 `201 Created`**：`{ "id": 6, "name": "招新", "color": "#007bff", "task_count": 0 }`（`task_count` 只读）。

**错误**：400 字段校验（重名等）；403 无 `common.manage_tags`。

### 标签详情与维护
`GET / PUT / PATCH / DELETE /tasks/tags/{id}/`

**认证**：登录；**权限**：读 —；写（PUT / PATCH / DELETE）需 `common.manage_tags`

- **GET**：响应 `200 OK` 单个标签对象；404 不存在。
- **PUT / PATCH**：请求体 `name` / `color`（PUT 需给全，PATCH 可局部）；响应 `200 OK` 标签对象；400 校验失败；403 无权限；404 不存在。
- **DELETE**：响应 `204 No Content`（解除任务关联，不删任务）；403 无权限；404 不存在。

### 模块路由根
`GET /tasks/`

**认证**：登录（DRF `DefaultRouter` 根视图沿用全局默认权限 `IsAuthenticated`）；**权限**：—

**响应 `200 OK`**：路由索引 JSON，含 `tasks`、`tags` 两个集合的列表 URL。供调试用，前端不调用。
