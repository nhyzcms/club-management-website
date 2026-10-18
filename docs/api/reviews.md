# 审核系统 API

审核系统（`/reviews/`）是职员侧的统一审核入口，台面上三张桌子：**发布审核**（新闻 / 活动 / 教程共用一条审核轴：通过 / 驳回 / 下架）、**意见反馈**（无对象投递箱：匿名 / 署名提交、了结）、**举报案**（有对象调查票：进行中 → 驳回 / 成立并处置）。身份审核不在本模块——身份审核端点在 accounts（`/auth/identity-reviews/`），见 [accounts.md](accounts.md)。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0017：统一审核系统](../adr/0017-unified-moderation-system.md)、[ADR-0003：不抽共享生命周期基类](../adr/0003-no-shared-task-proposal-lifecycle-base.md)、[ADR-0004：署名反馈媒体上传](../adr/0004-feedback-media-tus-resumable-upload.md)、[ADR-0005：访问控制原则](../adr/0005-access-control-principle.md)

## 概念与约定

- 三个资源挂载于同一前缀（`reviews/urls.py`，DRF Router）：`/reviews/reviews/` 发布审核、`/reviews/feedbacks/` 意见反馈、`/reviews/reports/` 举报案。`GET /reviews/` 为 Router 根视图，仅列出子资源，不是业务端点。
- 权限代号（`Meta.permissions`，ADR-0017）：`reviews.moderate`（发布审核）、`reviews.read_feedback`（查看并了结意见反馈）、`reviews.handle_report`（处理举报案）。`reviews.force_publish`（免审发布）作用于内容的创建路径，不经过本模块端点。
- **审核（Review）**状态机（`reviews/lifecycle.py`）：`pending` 待审 →`approved` 通过 / `rejected` 驳回；`approved` →`removed` 下架；`removed` 可再 `approve` 重新上架。**驳回评语必填**，通过 / 下架评语选填。审核行恰好挂一个父级（新闻 / 活动 / 教程），只门控「公开展示」，不改对象自身生命周期。
- 免审直通：持 `reviews.force_publish` 或站点策略 `content_review_enabled` 关闭时，新对象创建即 `approved`，不出现在待审队列。
- 审核动作写**通知**（category=`review`）：`approved` / `rejected` / `removed` 通知宿主主人（新闻作者 / 活动发起人 / 教程上传者）；反馈了结通知署名提交者。前端能力布尔见 [accounts.md](accounts.md)（`can_review_content` / `can_view_feedback` / `can_handle_reports`）。
- 对象侧的审核投影（`review_status` / `review_comment`、作者预览）见 [news.md](news.md)、[activities.md](activities.md)、[tutorials.md](tutorials.md)。征集作品的**复审**（录用 / 退稿）不是本模块的「审核」，见 [activities.md](activities.md)。
- 列表端点统一走全局分页（`page` 参数，每页 20；响应为 `count` / `next` / `previous` / `results` 信封）。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | `/reviews/reviews/` | 登录 | `reviews.moderate` | 发布审核队列（三类统一轴，可按状态过滤） |
| GET | `/reviews/reviews/{id}/` | 登录 | `reviews.moderate` | 单条审核条目 |
| POST | `/reviews/reviews/{id}/approve/` | 登录 | `reviews.moderate` | 通过（待审 / 已下架 → 通过） |
| POST | `/reviews/reviews/{id}/reject/` | 登录 | `reviews.moderate` | 驳回（评语必填） |
| POST | `/reviews/reviews/{id}/remove/` | 登录 | `reviews.moderate` | 下架（已通过 → 下架） |
| POST | `/reviews/feedbacks/submit/` | 公开 | — | 提交意见反馈（匿名 / 署名） |
| GET | `/reviews/feedbacks/` | 登录 | `reviews.read_feedback` | 意见反馈列表 |
| GET | `/reviews/feedbacks/{id}/` | 登录 | 署名创建人本人或 `reviews.read_feedback` | 反馈详情 |
| POST | `/reviews/feedbacks/{id}/close/` | 登录 | `reviews.read_feedback` | 了结反馈 |
| POST | `/reviews/reports/` | 已认证 | — | 提交举报（附到进行中案或开新案） |
| GET | `/reviews/reports/` | 登录 | `reviews.handle_report` | 举报案列表 |
| GET | `/reviews/reports/{id}/` | 登录 | `reviews.handle_report` | 举报案详情 |
| POST | `/reviews/reports/{id}/dismiss/` | 登录 | `reviews.handle_report` | 驳回举报案 |
| POST | `/reviews/reports/{id}/uphold/` | 登录 | `reviews.handle_report` | 成立并处置 |

## 端点详情

### 发布审核队列

`GET /reviews/reviews/`

**认证**：登录；**权限**：`reviews.moderate`

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `status` | string | 否 | 按审核状态过滤：`pending` / `approved` / `rejected` / `removed`；省略返回全部 |
| `ordering` | string | 否 | 排序字段：`created_at` / `reviewed_at`，前缀 `-` 为降序；默认 `-created_at` |
| `page` | integer | 否 | 页码（全局分页，每页 20） |

**响应 `200 OK`**

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 12,
      "status": "pending",
      "comment": "",
      "reviewer": null,
      "reviewed_at": null,
      "target_type": "news",
      "target_id": 34,
      "title": "秋季运动会摄影记录",
      "created_at": "2026-09-18T09:12:30Z",
      "updated_at": "2026-09-18T09:12:30Z"
    }
  ]
}
```

`target_type` 取值 `news` / `activity` / `tutorial`（无父级的坏数据时为 `null`）；`target_id` 为对应对象主键，`title` 取对象标题。已审条目会带上 `comment` 与 `reviewer`（轻量用户引用：`id` / `username` / `nickname` / `avatar`）、`reviewed_at`。

**错误**：403 未登录或未持 `reviews.moderate`。

### 审核条目详情

`GET /reviews/reviews/{id}/`

**认证**：登录；**权限**：`reviews.moderate`

返回队列中单条同形对象（200）。403 同上；404 条目不存在。

### 通过

`POST /reviews/reviews/{id}/approve/`

**认证**：登录；**权限**：`reviews.moderate`

**请求体**：`comment`（string，选填）— 审核评语。

**响应 `200 OK`**：单条审核条目，`status` 变为 `approved`，`reviewer` / `reviewed_at` 记为操作者与当前时间；通知宿主主人（事件 `approved`）。对象随即对公众可见。

**错误**：400 当前状态非 `pending` / `removed`（`{"detail": "当前状态不可执行该审核动作"}`）；403；404。

### 驳回

`POST /reviews/reviews/{id}/reject/`

**认证**：登录；**权限**：`reviews.moderate`

**请求体**：`comment`（string，**必填**，去空白后非空）— 驳回评语，作者可在自己的预览中看到。

```json
{ "comment": "标题与正文不符，请修改后重新提交" }
```

**响应 `200 OK`**：单条审核条目，`status` 变为 `rejected`；通知宿主主人（事件 `rejected`）。对象保持不公开。

**错误**：400 评语为空（`{"detail": "请填写驳回评语"}`）；400 当前状态非 `pending`（`{"detail": "当前状态不可执行该审核动作"}`）；403；404。

### 下架

`POST /reviews/reviews/{id}/remove/`

**认证**：登录；**权限**：`reviews.moderate`

**请求体**：`comment`（string，选填）— 下架原因。

**响应 `200 OK`**：单条审核条目，`status` 变为 `removed`，对象从公开列表 / 详情消失；通知宿主主人（事件 `removed`）。

**错误**：400 当前状态非 `approved`（`{"detail": "当前状态不可执行该审核动作"}`）；403；404。

### 提交意见反馈

`POST /reviews/feedbacks/submit/`

**认证**：公开；**权限**：—

两种提交方式：**匿名**（默认；未登录只能走这条，仅纯文字）不记录提交者身份；**署名**须登录并显式声明 `disclose_identity=true`，身份对处理人可见，且可附媒体证据——附件经 attachments 接口上传，要求署名创建者本人、了结前（见 [attachments.md](attachments.md)）。站点启用 Turnstile 时，**匿名**请求须带人机校验 token；已登录请求跳过。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | 是 | 标题（≤200 字符） |
| `description` | string | 否 | 详细说明，缺省为空串 |
| `category` | string | 是 | 类别：`suggestion` 建议 / `complaint` 投诉 / `other` 其他（举报不是反馈类别，走举报案） |
| `contact` | string | 否 | 联系方式（≤100 字符），缺省为空串 |
| `disclose_identity` | boolean | 否 | 默认 `false`（匿名）；`true` 时须登录，反馈记入 `creator` |
| `turnstile_token` | string | 否 | 仅匿名且站点启用 Turnstile 时必带；已登录忽略 |

```json
{
  "title": "希望延长广播站开放时间",
  "description": "下午放学后 18:00 前能进录音间更好。",
  "category": "suggestion",
  "disclose_identity": true
}
```

**响应 `201 Created`**

```json
{
  "id": 21,
  "status": "pending",
  "title": "希望延长广播站开放时间",
  "description": "下午放学后 18:00 前能进录音间更好。",
  "category": "suggestion",
  "contact": "",
  "creator": { "id": 7, "username": "member", "nickname": "小李", "avatar": null },
  "closed_by": null,
  "closed_at": null,
  "close_note": "",
  "attachments": [],
  "created_at": "2026-09-18T09:30:00Z",
  "updated_at": "2026-09-18T09:30:00Z"
}
```

匿名提交时 `creator` 为 `null`。`attachments` 为附件对象数组（`id` / `file_url` / `file_type` / `file_name` / `file_size` / `uploaded_by` / `uploaded_at`）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | `category` 非法（`{"category": ["类别须为建议、投诉或其他"]}`）；必填字段缺失或格式错误（DRF 字段级报错） |
| 400 | 未登录却声明署名（`{"detail": "署名提交需要登录"}`） |
| 400 | 匿名提交未过人机校验（`{"detail": "人机校验失败，请刷新后重试。"}`，仅站点启用 Turnstile 时） |
| 429 | 匿名节流：每 IP 每天 N 条（N 由站点策略 `feedback_anon_per_ip_per_day` 决定，默认 10；已登录请求不计入） |

### 意见反馈列表

`GET /reviews/feedbacks/`

**认证**：登录；**权限**：`reviews.read_feedback`（非持有人 403；本人署名反馈请走详情）

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `status` | string | 否 | `pending` 待处理 / `closed` 已了结 |
| `category` | string | 否 | `suggestion` / `complaint` / `other` |
| `search` | string | 否 | 在 `title`、`description` 中查找 |
| `ordering` | string | 否 | `created_at` / `updated_at`，默认 `-created_at` |
| `page` | integer | 否 | 页码（全局分页，每页 20） |

**响应 `200 OK`**

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 21,
      "status": "pending",
      "title": "希望延长广播站开放时间",
      "category": "suggestion",
      "contact": "",
      "creator": { "id": 7, "username": "member", "nickname": "小李", "avatar": null },
      "close_note": "",
      "attachment_count": 0,
      "created_at": "2026-09-18T09:30:00Z",
      "updated_at": "2026-09-18T09:30:00Z"
    }
  ]
}
```

匿名反馈的 `creator` 为 `null`。列表不含 `description` / `attachments`，详情才返回。

**错误**：403 未登录或未持 `reviews.read_feedback`。

### 意见反馈详情

`GET /reviews/feedbacks/{id}/`

**认证**：登录；**权限**：署名创建人本人，或 `reviews.read_feedback`

**响应 `200 OK`**：与提交反馈响应同形的详情对象（含 `description` 与 `attachments`）。

**错误**：403 未登录；404 反馈不存在或不在可查范围（非持有人查询他人反馈按 404 处理）。

### 了结意见反馈

`POST /reviews/feedbacks/{id}/close/`

**认证**：登录；**权限**：`reviews.read_feedback`

**请求体**：`note`（string，选填）— 了结说明。

```json
{ "note": "已线下跟进，调整后的开放时间下周生效" }
```

**响应 `200 OK`**：详情对象，`status` 变为 `closed`，`closed_by` / `closed_at` / `close_note` 落库。**署名**反馈会通知提交者（事件 `closed`）；匿名反馈无提交者，不通知。

**错误**：400 已了结（`{"detail": "当前状态不可了结"}`）；403；404。

### 提交举报

`POST /reviews/reports/`

**认证**：已认证（登录且任一认证通道通过）；**权限**：—

对**作为普通读者可见、且非自己**的新闻 / 活动 / 教程 / 评论 / 用户提交。同一对象同一时刻至多一张**进行中**案：第二人举报会作为新的一份举报附到该案上；同一人重复举报同一对象、或对象不可见 / 属于自己，都会被拒。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `target_type` | string | 是 | `news` / `activity` / `tutorial` / `comment` / `user` |
| `target_id` | integer | 是 | 对象主键 |
| `reason` | string | 是 | 举报理由（去空白后非空） |

```json
{ "target_type": "news", "target_id": 34, "reason": "内容含未经核实的指控" }
```

**响应 `201 Created`**

```json
{ "id": 5, "status": "open", "target_type": "news", "target_id": 34 }
```

`status` 为 `open`：新案即 `open`，附到既有进行中案时同样是 `open`；两种情况都返回 201 与案子的 `id`。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | `请填写举报理由` / `不支持的举报对象`（类型不在列表、`target_id` 非整数）/ `不能举报该对象`（对象不存在或对举报人不可见）/ `不能举报自己的内容` / `你已举报过该对象`（均为 `{"detail": …}`） |
| 403 | 未登录或未完成账号认证 |
| 429 | 举报节流：每用户每天 N 条（N 由站点策略 `reports_per_user_per_day` 决定，默认 10） |

### 举报案列表

`GET /reviews/reports/`

**认证**：登录；**权限**：`reviews.handle_report`

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `status` | string | 否 | `open` 进行中 / `dismissed` 驳回 / `upheld` 成立并处置 |
| `ordering` | string | 否 | `created_at` / `resolved_at`，默认 `-created_at` |
| `page` | integer | 否 | 页码（全局分页，每页 20） |

**响应 `200 OK`**

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 5,
      "status": "open",
      "target_type": "comment",
      "target_id": 88,
      "title": "这条内容纯属造谣……",
      "resolved_by": null,
      "resolved_at": null,
      "resolution_comment": "",
      "filings": [
        {
          "id": 6,
          "reporter": { "id": 9, "username": "reporter", "nickname": "阿黄", "avatar": null },
          "reason": "含人身攻击",
          "created_at": "2026-09-18T10:00:00Z"
        }
      ],
      "created_at": "2026-09-18T10:00:00Z",
      "updated_at": "2026-09-18T10:00:00Z"
    }
  ]
}
```

`title` 的取法：新闻 / 活动 / 教程取对象标题；评论取正文前 80 字（超出加 `…`）；用户取 `username`。`filings` 为该案下全部举报（每举报人一份）。

### 举报案详情

`GET /reviews/reports/{id}/`

**认证**：登录；**权限**：`reviews.handle_report`

返回列表中单案同形对象（200）。403 同上；404 案件不存在。

### 驳回举报案

`POST /reviews/reports/{id}/dismiss/`

**认证**：登录；**权限**：`reviews.handle_report`

**请求体**：`comment`（string，**必填**，去空白后非空）— 驳回理由。

```json
{ "comment": "经核实内容属实，不构成违规" }
```

**响应 `200 OK`**：案件对象，`status` 变为 `dismissed`，`resolved_by` / `resolved_at` / `resolution_comment` 落库。

**错误**：400 `{"detail": "该举报案已结案"}`（非进行中）；400 `{"detail": "请填写驳回理由"}`；403；404。

### 成立并处置

`POST /reviews/reports/{id}/uphold/`

**认证**：登录；**权限**：`reviews.handle_report`

成立即按对象执行**默认处置**（ADR-0017 决策 4）：新闻 / 活动 / 教程把对应审核行置为**下架**（无审核行或非「通过」时不动该行，只结案；已下架则幂等）；评论执行墓碑处置；用户执行**全站禁言**。处置不要求操作者另持 `reviews.moderate` / `messaging` 权限。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `comment` | string | 否 | 处理说明，落 `resolution_comment`（用户对象时作禁言理由） |
| `ends_at` | string | 否 | 禁言结束时间（ISO 8601，如 `2026-10-02T12:00:00+08:00`）；仅 `target_type=user` 有效，省略即永久禁言 |

```json
{ "comment": "确认违规，禁言两周", "ends_at": "2026-10-02T12:00:00+08:00" }
```

**响应 `200 OK`**：案件对象，`status` 变为 `upheld`，`resolved_by` / `resolved_at` / `resolution_comment` 落库。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | `{"detail": "该举报案已结案"}`（非进行中）；`{"detail": "结束时间格式无效"}`（`ends_at` 非空但无法解析） |
| 400 | 处置被拒：`不能禁言自己` / `该用户已被禁言` / `结束时间须晚于当前时间`（均为 `{"detail": …}`） |
| 403 | 未登录或未持 `reviews.handle_report` |
| 404 | 案件不存在 |
