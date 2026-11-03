# 活动 API（`events`）

「活动」是与「**互动**」（`activities`，众议 / 征集 / 展示 / 调研）并列的另一种内容：**有明确的起止时间窗，且允许参与者之间发生关系**（配对 / 组队 / 互评 / 接力等）。互动是星形结构（中心向成员发起，成员各自交回东西），活动是网状结构——两者拓扑不同，所以没有合并成一个 app。

本 app 目前只提供活动的**壳**：标题 / 简介 / 正文 / 组织者 / 时间窗 / 状态 / 可见性 / 形态键。具体参与方式放在 `events/modules/<key>/`，由 `module_key` 指向；**留空 = 纯展示型活动**（公告性质，只有内容与时间窗）。形态模块尚未接入，前端详情页对非空 `module_key` 显示「该形态尚未接入」。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：状态机与访问控制分离遵循 [ADR-0003](../adr/0003-no-shared-task-proposal-lifecycle-base.md)；权限命名遵循 [ADR-0005](../adr/0005-access-control-principle.md)。

## 模块约定

- **路径前缀**：`config/urls.py` 把本 app 挂在 `/events/`，`SimpleRouter` 以空前缀注册 `EventViewSet` → 列表 / 详情为 `/events/` 与 `/events/{id}/`。
- **状态机**（判定与流转真源 `events/lifecycle.py`；**惰性流转，无定时任务**——每次读取列表 / 详情时先 `lifecycle.touch()`）：

```text
draft ──publish──▶ scheduled ──到 start_at──▶ active ──到 end_at──▶ ended ──archive──▶ archived
                      └──── start_at 已过时发布 ────▶ active
```

  - `draft`：只有组织者与 `events.manage_events` 持有者可见；可任意编辑、可删除。
  - `scheduled`：已发布、未开始；仍可编辑（改时间 / 内容）。
  - `active`：进行中；**锁定编辑**（改时间会让已报名的参与者困惑），可参与（形态模块的写入口须先 `touch()` 再判 `can_participate()`）。
  - `ended`：到 `end_at` 自动结束；只读、不可参与。
  - `archived`：组织者 / 管理员手动归档，从默认列表收起，数据保留。
  - `end_at` 留空 = 不自动关闭，活动会一直停在 `active`。
- **审核轴尚未接入**：`Review` 当前只支持新闻 / 互动 / 教程；活动发布不经过审核队列。
- **通知尚未接入**：`lifecycle.touch()` 会返回本次到点开启 / 结束的 pk 列表，但暂无调用方发通知——「到点主动通知」需要额外的定时任务，不在本期范围。

## 数据字段

| 字段 | 类型 | 读 / 写 | 说明 |
|---|---|---|---|
| `id` | int | 只读 | |
| `title` | string | 读写 | ≤ 200 字 |
| `summary` | string | 读写 | ≤ 300 字，可空 |
| `body` | string（HTML） | 读写 | 写入时经 `common.rich_text.sanitize_html` 清洗 |
| `organizer` | object | 只读 | `SimpleUserSerializer`（`id` / `username` / `nickname` / `avatar`） |
| `start_at` | datetime | 读写 | **必填**；创建时必传 |
| `end_at` | datetime / null | 读写 | 可空（= 不自动关闭）；提供时必须晚于 `start_at`（否则 400 `end_at`） |
| `status` | string | 只读 | `draft` / `scheduled` / `active` / `ended` / `archived`；创建恒为 `draft`，只能经 publish / archive / 惰性流转改变 |
| `status_label` | string | 只读 | 状态中文名（草稿 / 待开始 / 进行中 / 已结束 / 已归档） |
| `visibility` | string | 读写 | `public`（公开，游客可见）/ `members`（仅成员，默认） |
| `visibility_label` | string | 只读 | 「公开」/「仅成员」 |
| `module_key` | string | 读写 | 形态模块键，≤ 40；留空 = 纯展示型。框架阶段不校验取值，未知键按展示型降级 |
| `created_at` / `updated_at` | datetime | 只读 | |

**创建**：认证「已认证」（`IsAuthenticated + IsVerified`）；`organizer` 取当前用户，`status` 恒为 `draft`。
**编辑 / 删除 / 发布 / 归档**：登录 + 组织者本人，或持 `events.manage_events`（对象级）。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | `/events/` | 公开 | — | 活动列表（分页；游客仅见公开受众的非草稿） |
| POST | `/events/` | 已认证 | — | 发起活动（恒为草稿） |
| GET | `/events/{id}/` | 公开 | — | 活动详情（可见性见下） |
| PUT / PATCH | `/events/{id}/` | 登录 | 组织者或 `events.manage_events` | 编辑（仅 `draft` / `scheduled`） |
| DELETE | `/events/{id}/` | 登录 | 组织者或 `events.manage_events` | 删除（仅 `draft`；已发布请归档） |
| POST | `/events/{id}/publish/` | 登录 | 组织者或 `events.manage_events` | 发布草稿 → `scheduled` / `active` |
| POST | `/events/{id}/archive/` | 登录 | 组织者或 `events.manage_events` | 归档（仅 `ended`） |

「认证」口径：公开 = `AllowAny`；登录 = 仅要求已登录（未登录 403）；已认证 = 登录且账号已通过任一认证通道（`accounts.IsVerified`，未认证 403）。

## 端点详情

### 活动列表

`GET /events/`

**认证**：公开；**权限**：—。查询范围按身份收窄：

- 游客：`visibility=public` 且非 `draft`；
- 已登录成员：全部非 `draft` + 自己发起的草稿；
- `events.manage_events` 持有者：全部（含草稿）。

**查询参数**

| 名称 | 类型 | 说明 |
|---|---|---|
| `status` | string | 按状态过滤：`draft` / `scheduled` / `active` / `ended` / `archived` |
| `visibility` | string | `public` / `members` |
| `module_key` | string | 按形态键过滤（空串筛展示型） |
| `search` | string | 搜索标题 / 简介 / 正文 |
| `ordering` | string | `start_at` / `end_at` / `created_at`（前缀 `-` 倒序；默认 `-start_at`、`-id`） |
| `page` | int | 页码，每页 20 条 |

**响应 `200 OK`**：分页信封 `{count, next, previous, results}`，条目结构见「数据字段」。

### 发起活动

`POST /events/`

**认证**：已认证；**权限**：—（登录即可发起，是否已认证由 `IsVerified` 把关）。

**请求体**

```json
{
  "title": "明信片互寄",
  "summary": "给一年后的自己写一张明信片",
  "body": "<p>活动说明……</p>",
  "start_at": "2026-11-05T09:00:00+08:00",
  "end_at": "2026-11-12T18:00:00+08:00",
  "visibility": "members",
  "module_key": ""
}
```

**响应 `201 Created`**：活动详情，`status` 为 `draft`，`organizer` 为当前用户。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | `start_at` 缺失 / 格式非法；`end_at` 早于或等于 `start_at`（`{"end_at": "结束时间必须晚于开始时间"}`） |
| 403 | 未登录或未认证 |

### 活动详情

`GET /events/{id}/`

**认证**：公开；**权限**：—。`draft` 仅组织者与 `events.manage_events` 持有者可见（其他人 404）；非草稿按 `visibility`：`public` 游客可见，`members` 仅登录成员可见。

**响应 `200 OK`**：活动详情（字段见上）。

**错误**：`404` 不存在 / 无权查看（草稿对其他成员同样 404，不暴露存在性）。

### 编辑活动

`PUT /events/{id}/`、`PATCH /events/{id}/`

**认证**：登录；**权限**：组织者或 `events.manage_events`。

**可编辑窗口**：仅 `draft` / `scheduled`。`active` 起锁定，`ended` / `archived` 不可改。

**请求体**：同创建（`status` / `organizer` / 时间戳只读）。`end_at` 仍须晚于 `start_at`。

**响应 `200 OK`**：更新后的活动详情。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | `end_at` 不晚于 `start_at` |
| 403 | 非组织者且无 `events.manage_events`；或活动已开始 / 已结束（`活动已开始，仅草稿或待开始期间可修改`） |
| 404 | 活动不可见 |

### 删除活动

`DELETE /events/{id}/`

**认证**：登录；**权限**：组织者或 `events.manage_events`。**仅 `draft` 可删**——已发布的活动请走归档，避免抹掉参与者已经看到的时间窗。

**响应 `204 No Content`**（无响应体）。

**错误**：`403` 非草稿（`仅草稿可以删除；已发布的活动请归档`）；`404` 不可见。

### 发布活动

`POST /events/{id}/publish/`

**认证**：登录；**权限**：组织者或 `events.manage_events`。仅 `draft` 可发布。

按 `start_at` 与当前时间决定目标状态：`start_at` 在未来 → `scheduled`，否则 → `active`。

**响应 `200 OK`**：活动详情（`status` 已更新）。

**错误**：`400` 非草稿（`detail` 提示「只有草稿可以发布」）。

### 归档活动

`POST /events/{id}/archive/`

**认证**：登录；**权限**：组织者或 `events.manage_events`。仅 `ended` 可归档。

**响应 `200 OK`**：活动详情（`status=archived`）。

**错误**：`400` 非已结束（`detail` 提示「只有已结束的活动可以归档」）。

## 权限与后台

- `events.manage_events`（「可管理任意活动」）：编辑 / 发布 / 归档任意活动，并可见全部草稿；能力投影为 `can_manage_events`（`GET /auth/me/`）。
- `events.manage_event_types`（「可装载 / 卸载活动形态」）：为形态模块注册表预留，**当前没有任何 API 消费它**——能力键集是冻结契约，暂不投影。
- Django admin：`活动 → 活动`（`EventAdmin`）提供列表 / 编辑，列表列含状态、可见性、形态键、时间窗与组织者；**发布 / 归档动作在门户完成**，后台只做数据修正（`status` 字段可直接改，无批量动作）。

## 前端入口

- 列表 `/#/events`：状态 tab（全部 / 进行中 / 待开始 / 已结束 / 已归档）；「发起活动」按钮对已认证用户显示。
- 发起 / 编辑 `/#/events/new`（当前只有新建表单；编辑入口尚未接入前端，可走 API 或后台）。
- 详情 `/#/events/:id`：正文 + 时间窗 + 组织者；组织者 / 管理员可见「发布」「归档」「删除草稿」动作。
- 手机版 `/#/m/events` 与 `/#/m/events/:id`；手机 UA 访问 `/events` 会自动改道到 `/m/events`。
