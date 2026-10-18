# 评论与消息 API

评论区（宿主为新闻 / 活动 / 任务）、1:1 私信、站内通知、全站禁言、横幅公告，以及推送用 WebSocket。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0005 访问控制原则](../adr/0005-access-control-principle.md)、[ADR-0010 运行时站点策略](../adr/0010-runtime-site-policy.md)、[ADR-0015 Channels 无 Redis：WebSocket 只推送](../adr/0015-channels-without-redis.md)、[ADR-0016 评论区与私信会话分离](../adr/0016-comment-thread-vs-dm.md)、[ADR-0017 统一审核系统](../adr/0017-unified-moderation-system.md)

挂载前缀 `/messaging/`，路由由 DRF `DefaultRouter` 生成：`/messaging/threads/`、`/messaging/comments/`、`/messaging/conversations/`、`/messaging/notifications/`、`/messaging/mutes/`、`/messaging/banners/`。写入规则（认证门禁、全站禁言、评论区状态、嵌套上限、3 分钟撤回、墓碑删除）集中在 `messaging/services.py`；HTTP 是事实源，WebSocket 只是推送适配器。举报案的默认处置（评论墓碑删除 / 全站禁言）由 reviews 的特权服务调用，不经本模块端点。

**通用规则速查**

- 评论区状态：`open`（开放）/ `muted`（评论区禁言：已有评论可见，不能再发言）/ `closed`（彻底关闭：普通读者看不到该区，协管仍可看可管）。
- 谁可见宿主，谁就可见其评论区：未公开新闻的评论区不对公众开放；活动按自身可见性；任务评论区需登录。`closed` 后仅协管可见。
- 拧状态 / 墓碑删评论：**宿主主人**（news 作者 / activity、task 创建人）或持 `messaging.manage_comment_thread`；不随「管理新闻 / 活动 / 任务」自动获得。
- 撤回窗口 3 分钟（评论与私信一致）；评论已有回复则不能撤回。
- 站点策略开关：`comments_enabled` 关闭 → 发评论 403「评论功能已关闭」；`dms_enabled` 关闭 → 发 / 发起私信 403「私信功能已关闭」（`get_policy()`，ADR-0010）。
- 未认证（`IsVerified`）与全站禁言（`IsNotMuted`）只拦**写**动作；被禁言者仍可登录、阅读、接收。
- 通知**未读聚合**：同一「未读事项」（源 × 事件 × 事项）只保留一条通知，读掉之后才重新通知（见「通知列表与详情」）。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | `/messaging/threads/?news=\|activity=\|task=` | 公开 | — | 按宿主取评论区（不存在则创建）|
| GET | `/messaging/threads/{id}/` | 公开 | — | 评论区详情（不可见 → 404）|
| PATCH | `/messaging/threads/{id}/` | 登录 | 宿主主人或 `messaging.manage_comment_thread` | 改评论区状态 |
| GET | `/messaging/comments/?thread=` | 公开 | — | 根评论分页（子评论嵌在 `replies`）|
| POST | `/messaging/comments/` | 已认证 | —（另受站点开关与全站禁言限制）| 发表评论 / 回复 |
| POST | `/messaging/comments/{id}/retract/` | 登录 | —（仅作者本人）| 撤回自己的评论 |
| POST | `/messaging/comments/{id}/delete/` | 登录 | 宿主主人或 `messaging.manage_comment_thread` | 墓碑删除评论 |
| GET | `/messaging/conversations/` | 登录 | — | 我的会话列表（分页）|
| POST | `/messaging/conversations/` | 登录 | — | 禁用，固定 405 |
| GET | `/messaging/conversations/{id}/` | 登录 | —（仅参与者）| 会话详情 |
| POST | `/messaging/conversations/{id}/send_message/` | 已认证 | —（仅参与者；另受全站禁言限制）| 发送私信 |
| POST | `/messaging/conversations/{id}/retract_message/` | 登录 | —（仅发送者本人）| 撤回私信 |
| POST | `/messaging/conversations/{id}/mark_read/` | 登录 | —（仅参与者）| 会话消息批量标已读（联动该会话未读通知）|
| GET | `/messaging/conversations/unread_count/` | 登录 | — | 私信未读总数（铃铛红点）|
| GET | `/messaging/conversations/messages/?conversation_id=` | 登录 | —（仅参与者）| 会话消息倒序分页 |
| POST | `/messaging/conversations/start_private/` | 已认证 | —（另受全站禁言限制）| 发起 / 复用 1:1 会话 |
| GET | `/messaging/notifications/` | 登录 | — | 我的通知列表（分页）|
| GET | `/messaging/notifications/{id}/` | 登录 | — | 通知详情（仅收件人）|
| GET | `/messaging/notifications/unread_count/` | 登录 | — | 未读通知数 |
| POST | `/messaging/notifications/{id}/mark_read/` | 登录 | — | 单条标已读 |
| POST | `/messaging/notifications/mark_read/` | 登录 | — | 全部标已读 |
| POST | `/messaging/mutes/` | 登录 | `messaging.mute_user` | 全站禁言 |
| POST | `/messaging/mutes/lift/` | 登录 | `messaging.mute_user` | 解除全站禁言 |
| GET | `/messaging/mutes/me/` | 登录 | — | 我的禁言状态 |
| GET | `/messaging/banners/current/` | 公开 | — | 当前横幅公告（无则 204）|
| WS | `/ws/messaging/` | 登录（会话 Cookie）| — | 推送通道（只推不收业务数据）|
| GET | `/messaging/` | 登录 | — | DRF 路由根（索引，自动生成）|

用户引用统一为 `{id, username, nickname, avatar}`（仅本人带 `email`）；时间字段为 UTC ISO 8601（如 `2026-09-19T04:30:00Z`）。

## 端点详情

### 取评论区（按宿主 / 按 id）
`GET /messaging/threads/` · `GET /messaging/threads/{id}/`

**认证**：公开；**权限**：—（不可见 → 404）

**查询参数**（仅无 id 的集合 URL）：`news` / `activity` / `task` 三选一且**必须恰好一个**（值为宿主 id）；按 id 取时 `can_see_thread` 不通过一律 404。

**响应 `200 OK`**

```json
{ "id": 57, "status": "open", "news": null, "activity": null, "task": 12, "can_manage": false }
```

按宿主取时评论区惰性创建（默认 `open`）；`can_manage` = 当前查看者可否改状态 / 墓碑删评论。

**错误**：400 未指定或指定多个宿主 → `请指定恰好一个宿主：news、activity 或 task`；404 宿主不存在 → `宿主不存在`；宿主不可见或评论区 `closed` 且非协管 → `评论区不存在`。

### 修改评论区状态
`PATCH /messaging/threads/{id}/`

**认证**：登录；**权限**：宿主主人或 `messaging.manage_comment_thread`

**请求体**：`{ "status": "muted" }`（必填，`open` / `muted` / `closed`）。

**响应 `200 OK`**：更新后的评论区对象（含 `can_manage`）。

**错误**：400 `状态须为 open、muted 或 closed`；403 `没有管理该评论区的权限`；404 不可见（含非协管看 `closed` 区）。

### 评论列表
`GET /messaging/comments/`

**认证**：公开；**权限**：—（评论区不可见 → 404）

**查询参数**：`thread`（int，必填，评论区 id）；`page`（页码，20 根评论/页，越界 404）。

**响应 `200 OK`**（分页只作用于根评论；子评论整体嵌套在 `replies`、递归、按 `created_at` 升序）

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    { "id": 901, "thread": 57, "author": { "id": 9, "username": "wang", "nickname": "王同学", "avatar": null },
      "parent": null, "content": "剪辑就交给你了", "retracted_at": null, "deleted_at": null,
      "created_at": "2026-09-19T03:00:00Z", "updated_at": "2026-09-19T03:00:00Z",
      "replies": [
        { "id": 902, "thread": 57, "author": { "id": 7, "username": "li", "nickname": "李同学", "avatar": null },
          "parent": 901, "content": "收到", "retracted_at": null, "deleted_at": null,
          "created_at": "2026-09-19T03:05:00Z", "updated_at": "2026-09-19T03:05:00Z", "replies": [] }
      ] }
  ]
}
```

墓碑删除的评论 `content` 固定返回 `该评论已删除`（`deleted_at` 非空）；撤回的评论保留原文、以 `retracted_at` 标记。**错误**：400 缺少 `thread`；404 评论区不存在 / 不可见。

### 发表评论
`POST /messaging/comments/`

**认证**：已认证；**权限**：—（另受站点开关、全站禁言与评论区状态限制）

**请求体**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| thread | int | 是 | 评论区 id |
| content | string | 是 | 去空白后非空 |
| parent | int | 否 | 父评论 id（须属于同一评论区）；缺省为根评论 |

**响应 `201 Created`**：单条评论对象（结构同上，`replies` 为 `[]`）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 缺少 `thread`；`父评论不存在`；`评论内容不能为空`；`评论区已禁言`；`评论区已关闭`；`超过最大嵌套层数`（上限 `comment_max_depth`，默认 8）|
| 403 | 站点 `comments_enabled` 关闭 → `评论功能已关闭`；未认证 → `请先完成账号认证后再使用此功能（发帖 / 发消息 / 建申报等）。`；被全站禁言 → `你已被全站禁言，暂时不能发言。` |
| 404 | 评论区不存在 / 不可见 |

发布成功向该区订阅者推送 `comment` 事件，并给被回复者 / 被 @ 的可见者写通知（类别 `comment`）。

### 撤回评论
`POST /messaging/comments/{id}/retract/`

**认证**：登录；**权限**：—（服务端要求评论作者本人）

**请求体**：无。**响应 `200 OK`**：评论对象（`retracted_at` 已写）。

**错误**：400 `评论已撤回`；`评论已删除`；`已有回复，不能撤回`；`已超过撤回时限`（3 分钟）。403 非作者 → `只能撤回自己的评论`。404 评论不存在 / 所在评论区不可见。

### 删除评论（墓碑）
`POST /messaging/comments/{id}/delete/`

**认证**：登录；**权限**：宿主主人或 `messaging.manage_comment_thread`

**请求体**：无。**响应 `200 OK`**：评论对象；`deleted_at` / `deleted_by` 已写，`content` 对外变为 `该评论已删除`，回复保留。**错误**：400 `评论已删除`；403 `没有管理该评论区的权限`；404 评论不存在 / 不可见。

### 会话列表（含禁用根）
`GET /messaging/conversations/` · `POST /messaging/conversations/`

**认证**：登录；**权限**：—（只返回自己参与的会话）

**查询参数**：`page`（20/页），按 `-updated_at` 排序。

**响应 `200 OK`**（分页信封）

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    { "id": 33, "title": "",
      "participants": [
        { "id": 9, "username": "wang", "nickname": "王同学", "avatar": null },
        { "id": 7, "username": "li", "nickname": "李同学", "avatar": null }
      ],
      "last_message": null, "unread_count": 1,
      "created_at": "2026-09-18T09:12:03Z", "updated_at": "2026-09-19T04:30:11Z" }
  ]
}
```

`last_message` 为最新一条消息（`MessageSerializer`，含已撤回者）或 `null`；`unread_count` 不含自己发出与被撤回的消息。

**`POST /messaging/conversations/` 固定返回 `405 Method Not Allowed`**：`{ "detail": "请使用 start_private 发起私信。" }`；本 ViewSet 只允许 GET / POST，更新与删除方法一律 405。

### 会话详情
`GET /messaging/conversations/{id}/`

**认证**：登录；**权限**：参与者（否则 404）

**响应 `200 OK`**：单个会话对象（同上）。**错误**：404 不存在或不参与。

### 发送私信
`POST /messaging/conversations/{id}/send_message/`

**认证**：已认证；**权限**：参与者（另受全站禁言限制）

**请求体**：`{ "content": "今晚有空吗？" }`（必填，去空白后非空；其中 `@username` 会解析进 `mentions`）。

**响应 `201 Created`**

```json
{ "id": 501, "conversation": 33,
  "sender": { "id": 7, "username": "li", "nickname": "李同学", "avatar": null },
  "content": "今晚有空吗？", "mentions": [], "is_read": false,
  "retracted_at": null, "created_at": "2026-09-19T04:30:11Z", "updated_at": "2026-09-19T04:30:11Z" }
```

`is_read` 表示当前用户是否已有该消息的已读记录；发送同时刷新会话 `updated_at`，并向对方推送 `dm` 事件。

**错误**：400 `消息内容不能为空`；403 站点 `dms_enabled` 关闭 → `私信功能已关闭`、未认证、全站禁言；404 会话不存在或不参与。

### 撤回私信
`POST /messaging/conversations/{id}/retract_message/`

**认证**：登录；**权限**：参与者（服务端要求发送者本人）

**请求体**：`{ "message_id": 501 }`（必填）。**响应 `200 OK`**：消息对象（`retracted_at` 已写）。**错误**：400 缺少 `message_id` → `缺少 message_id`、`消息已撤回`、`已超过撤回时限`；403 `只能撤回自己的消息`；404 `消息不存在`（或会话不存在 / 不参与）。

### 标记会话已读
`POST /messaging/conversations/{id}/mark_read/`

**认证**：登录；**权限**：参与者

**请求体**：无。**响应 `200 OK`**：`{ "detail": "已标记为已读" }`。为会话中当前用户尚无已读记录的消息写入已读（幂等），清空该会话未读徽标。

**联动**：同时把该会话的**未读私信通知**标为已读（含聚合上线前的存量行）——“读私信 ⇒ 通知也不再亮着”，不论从通知入口点进来还是直接开私信页读的。

### 私信未读总数
`GET /messaging/conversations/unread_count/`

**认证**：登录；**权限**：—

**响应 `200 OK`**：`{ "total": 2 }`。只统计自己参与的会话中**他人发来**的未撤回且未读消息（自己发的不计，否则红点常亮）。

### 会话消息（倒序分页）
`GET /messaging/conversations/messages/`

**认证**：登录；**权限**：参与者（非参与者按 404）

**查询参数**：`conversation_id`（int，必填）；`page`（20/页；`page=1` 为最新一页，`next` 非空即还有更早）。

**响应 `200 OK`**：分页信封，条目为 `MessageSerializer`，按 `-created_at` 倒序（前端「最新优先 + 向上加载更早」）。**错误**：400 `缺少 conversation_id`；404 `会话不存在`（含不参与）、越界页 404。

### 发起私信
`POST /messaging/conversations/start_private/`

**认证**：已认证；**权限**：—（另受全站禁言限制）

**请求体**：`{ "user_id": 7 }`（必填，对方须已认证）。

**响应**：新建返回 `201 Created`，已有 1:1 会话则复用返回 `200 OK`；正文均为会话对象（结构同会话列表条目）。

**错误**：400 缺少 `user_id`、`不能和自己对话`、`对方尚未完成认证`；403 站点 `dms_enabled` 关闭 → `私信功能已关闭`、自己已被全站禁言；404 `用户不存在`。

### 通知列表与详情
`GET /messaging/notifications/` · `GET /messaging/notifications/{id}/`

**认证**：登录；**权限**：—（查询集限定 `recipient=当前用户`，他人通知按 404）

**查询参数**：列表支持 `page`（20/页），按 `-created_at`。

**响应 `200 OK`**（列表为分页信封，条目如下；详情直接返回该对象）

```json
{ "id": 71, "category": "comment", "event": "comment_replied",
  "payload": { "comment_id": 902, "thread_id": 57, "parent_id": 901,
    "news_id": null, "activity_id": null, "task_id": 12,
    "actor_id": 9, "actor_username": "wang" },
  "read_at": null, "created_at": "2026-09-19T03:06:00Z" }
```

`payload` 为 JSON 对象，字段随类别不同（见下表）；`actor_id` / `actor_username` 在系统自动事件（如禁言到期）中缺省。落库时按收件人订阅偏好（`/messaging/notification-preferences/`）投递外发通道（如邮件）：默认**异步**（进程内队列 + 守护线程，失败按退避重试至多 5 次、超限落 `failed` 留痕，不影响站内通知；重启残漏由周期扫描补投）；`NOTIFICATIONS_DELIVERY_ASYNC=0` 可回退旧同步投递。见 [ADR-0024](../adr/0024-async-notification-delivery.md)。

**未读聚合（同一事项只提示一次）**：通知源可声明**聚合键**（``源:事件:事项``，实现见 `messaging/notifications/registry.py`）。同一聚合键在**未读**期间只保留一条通知：后续同事项不新建行，只并入既有那条（`payload.count` 累加、`last_at` 刷新），并再推一次 `notification` 事件（前端据此刷新列表与徽标）；**被读掉之后**下一条同事项才重新通知。聚合命中的不重复外发（邮件等）——“一个未读事项 = 至多一封邮件”。目前只有私信声明了聚合键（`dm:new_message:<会话 id>`），其余源每条事件各自一条通知。

| category | event | 触发 | payload（公共字段之外）|
|---|---|---|---|
| `comment` | `comment_replied` | 有人回复你的评论 | `comment_id`、`thread_id`、`parent_id`、`news_id` / `activity_id` / `task_id` |
| `comment` | `comment_mentioned` | 评论中 @ 你（你能看见该宿主才通知）| 同上 |
| `dm` | `new_message` | 收到新私信（**按会话聚合**：同会话连发多条只提示一次，直到读掉）| `type` = `dm`、`id`（会话 id）、`title`、`url`；聚合后附 `count`（累计条数）、`last_at` |
| `validity` | `expiring_2m` / `expiring_1m` | 认证 / 管理员身份**到期前**两个月 / 一个月（到期会降权，见[身份认证指南](../guides/certification.md#到期前提醒降权预警））| `channel`、`channel_label`、`level`、`expires_on`、`days_left`、`url`（认证面板）|
| `review` | `approved` / `rejected` / `removed` | 发布审核通过 / 驳回 / 下架（通知宿主主人）| `type`（news / activity / tutorial）、`id`、`url` |
| `review` | `closed` | 署名意见反馈了结 | `type` = `feedback`、`id`、`url`（有 note 时附 `reason`）|
| `discipline` | `muted` / `mute_lifted` / `mute_expired` | 全站禁言授予 / 解除 / 到期惰性解除 | `mute_id`（`muted` 另附 `reason`、`ends_at`）|

### 通知未读数
`GET /messaging/notifications/unread_count/`

**认证**：登录；**权限**：—；**响应 `200 OK`**：`{ "total": 3 }`（`read_at` 为空的通知数）。

### 单条通知已读
`POST /messaging/notifications/{id}/mark_read/`

**认证**：登录；**权限**：—（仅收件人）

**响应 `200 OK`**：更新后的通知对象（首次标记写 `read_at`，重复调用幂等）。**错误**：404 不存在或非收件人。

### 全部通知已读
`POST /messaging/notifications/mark_read/`

**认证**：登录；**权限**：—

**响应 `200 OK`**：`{ "detail": "已全部标为已读" }`（只更新未读行，不推送）。

### 全站禁言
`POST /messaging/mutes/`

**认证**：登录；**权限**：`messaging.mute_user`

**请求体**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| user_id | int | 是 | 被禁言用户 id |
| reason | string | 否 | 理由，可空 |
| ends_at | string | 否 | 结束时间（ISO 8601；解析失败 → 400；无时区信息按 `TIME_ZONE` 补全，当前为 UTC）；缺省为永久 |

**响应 `201 Created`**

```json
{ "id": 5, "user": 13, "muted_by": 1, "reason": "发布不当言论",
  "starts_at": "2026-09-19T05:00:00Z", "ends_at": "2026-09-26T05:00:00Z", "lifted_at": null }
```

`user` / `muted_by` 为纯用户 id。禁言生效后向被禁言者写 `discipline` 通知（`muted`）。

**错误**：400 缺少 `user_id`、`ends_at 格式无效`、`不能禁言自己`、`该用户已被禁言`、`结束时间须晚于当前时间`；403 无 `messaging.mute_user` → `没有全站禁言权限。`；404 `用户不存在`。

### 解除全站禁言
`POST /messaging/mutes/lift/`

**认证**：登录；**权限**：`messaging.mute_user`

**请求体**：`{ "user_id": 13 }`（必填）。**响应 `200 OK`**：被解除的禁言行（`lifted_at` 已写），并向该用户写 `discipline` 通知（`mute_lifted`）。**错误**：400 缺少 `user_id`、`该用户未被禁言`；403 无权限；404 `用户不存在`。

### 我的禁言状态
`GET /messaging/mutes/me/`

**认证**：登录；**权限**：—

**响应 `200 OK`**：`{ "muted": true, "mute": { …UserMuteSerializer… } }`；未被禁言时 `{ "muted": false, "mute": null }`。读取时会惰性解除已到期的禁言（并写 `mute_expired` 通知）。

### 当前横幅公告
`GET /messaging/banners/current/`

**认证**：公开；**权限**：—

**响应**：无生效横幅返回 `204 No Content`（空正文，前端按 `null` 处理）；有则 `200 OK`：

```json
{ "id": 3, "body": "本周五 18:00 招新面试，地点 B203。", "link": "/news/12",
  "starts_at": "2026-09-18T00:00:00Z", "ends_at": "2026-09-25T00:00:00Z", "priority": 10 }
```

生效窗口 `starts_at <= now < ends_at`，同刻只出一条：`priority` 高者胜，并列取较新（`-created_at`）。写入只走 Django admin，无 HTTP 写端点。

### 消息推送 WebSocket
`WS /ws/messaging/`

**认证**：登录——Channels `AuthMiddlewareStack`（会话 Cookie + `AllowedHostsOriginValidator`）；未登录连接被服务端直接关闭（`connect` 内 `close()`，不 accept）。

连接即自动加入个人组 `user_{id}`（无需订阅）；订阅评论区后另加入 `thread_{id}`。**只推送，不收业务数据**（HTTP 是事实源）。

**客户端 → 服务端**（JSON 文本）

| 消息 | 说明 |
|---|---|
| `{ "action": "subscribe_thread", "thread_id": 57 }` | 订阅评论区；`thread_id` 非正整数、或评论区不可见时静默忽略 |
| `{ "action": "unsubscribe_thread", "thread_id": 57 }` | 退订评论区 |

非 dict 消息、其他 action 一律忽略。

**服务端 → 客户端**（仅推送）

```json
{ "event": "comment", "payload": { "thread_id": 57, "comment_id": 901 } }
```

| event | 组 | payload | 触发 |
|---|---|---|---|
| `comment` | `thread_{id}`（需已订阅）| `thread_id`、`comment_id`；撤回附 `"retracted": true`，墓碑删除附 `"deleted": true` | 发表 / 撤回 / 删除评论 |
| `dm` | `user_{id}`（自动，无需订阅）| `conversation_id`、`message_id`；撤回附 `"retracted": true` | 发送 / 撤回私信 |
| `notification` | `user_{id}` | `notification_id`、`category`、`event` | 通知落库（`notify()`）后；聚合命中并入既有未读时也推 |

推送仅作提示，前端据此重拉 HTTP；Channels 未接线时服务端静默 no-op（ADR-0015）。

### 模块路由根
`GET /messaging/`

**认证**：登录（DRF `DefaultRouter` 根视图沿用全局默认权限 `IsAuthenticated`）；**权限**：—；**响应 `200 OK`**：路由索引 JSON，列出六个集合的列表 URL。供调试用，前端不调用。
