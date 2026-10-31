# 活动 API

社团成员发起的四类活动（众议 / 征集 / 展示 / 调研）的创建、参与、布展与生命周期接口，全部由 `activities/urls.py` 的 `DefaultRouter`（`ActivityViewSet`）暴露。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0007](../adr/0007-activity-independent.md)、[ADR-0011](../adr/0011-survey-activity-type.md)、[ADR-0014](../adr/0014-questionnaire-independent.md)、[ADR-0017](../adr/0017-unified-moderation-system.md)、[ADR-0019](../adr/0019-public-audience-voting.md)

## 模块约定

- **路径前缀**：`config/urls.py` 把本 app 挂在 `/activities/`，router 内又注册了 `activities` → 全部端点形如 `/activities/activities/…`；`GET /activities/` 只是 DRF 路由根（罗列路由名），无业务语义。
- **类型与状态机**（判定真源 `activities/state.py::calc_state`，守卫在 `activities/lifecycle.py`；惰性流转，无定时任务）。
  - 落库的 `status` 是**最近一次结算的快照**：读入口（列表 / 详情）会先跑惰性流转再返回，但任何时刻都应以 `calc_state` 的判定为准（如「已过截止但快照仍是 open」在判定层已按已结束处理）。
  - 众议 `deliberation`：`scheduled`（待开始）→ `open`（投票中）→ `closed`（已截止）
  - 征集 `collection`：`scheduled` → `collecting`（收件中）→ `reviewing`（复审中）→ `archived`；`review_enabled=false` 时跳过复审，收件结束直接 `archived`
  - 展示 `exhibition`：`scheduled` → `open`（展示中）→ `closed`；调研 `survey`：`scheduled` → `open`（征答中）→ `closed`
  - 设未来的 `start_at` 即进入 `scheduled`，到点自动开放（征集→`collecting`，其余→`open`）；到 `end_at` 自动结算众议 / 展示 / 调研。**征集到 `end_at` 立即停止收件**（判定层即时生效），落库状态由读入口惰性推进到 `reviewing` / `archived`（按 `review_enabled`）；`max_submissions` 满额同样收口。
  - **长期活动**（`is_permanent=true`）：不设截止，`end_at` 恒为 `null`，永不被时间自动结算；只能由发起人或持 `activities.manage_activity` 者调用 `close` 手动终结。`is_permanent` 与 `end_at` 二选一（勾选长期时传 `end_at` 会 400）。征集的 `max_submissions` 满额自动收口仍然生效（数量上限是显式配置，与时间无关）。
- **审核轴**（`reviews` app，[ADR-0017](../adr/0017-unified-moderation-system.md)）：`review_status` ∈ `pending` / `approved` / `rejected` / `removed` / `null`（尚无审核行），只门控「公开展示」，不阻断活动自身状态机。列表 / 详情只出已过审（或无审核行）的活动；自己发起的全部活动（含待审 / 驳回 / 下架）走 `mine` 预览。
- **`owed`**（列表 / 详情字段）：`vote` / `submit` / `null`——已认证成员在「投票中且未投」「收件中且未投」「展示中启用投票且未投」时欠的行动；仅对已认证成员计算。
- **`X-Device-Id`**：访客调研作答 / 公开受众投票的设备标识（门户写入 localStorage 的 UUID）；缺失或非法按无标识处理。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | `/activities/activities/` | 公开 | — | 活动列表（分页；访客仅见公开受众的调研与众议 / 展示） |
| POST | `/activities/activities/` | 已认证 | — | 发起活动（创建即开审核） |
| GET | `/activities/activities/{id}/` | 公开 | — | 活动详情（访客仅公开受众的调研与众议 / 展示） |
| PUT | `/activities/activities/{id}/` | 登录 | 发起人或 `activities.manage_activity` | 全量更新（仅待开始；调研 Schema 见下） |
| PATCH | `/activities/activities/{id}/` | 登录 | 发起人或 `activities.manage_activity` | 局部更新（同上） |
| DELETE | `/activities/activities/{id}/` | 登录 | 发起人或 `activities.manage_activity` | 删除活动（无状态门禁） |
| GET | `/activities/activities/mine/` | 登录 | — | 我发起的活动（含待审 / 驳回 / 下架） |
| POST | `/activities/activities/{id}/vote/` | 公开 / 已认证 | — | 投选票（众议；启用投票的展示；公开受众游客可投） |
| POST | `/activities/activities/{id}/respond/` | 公开 | — | 调研作答（访客需设备标识） |
| GET | `/activities/activities/{id}/responses/` | 登录 | — | 问卷作答查看（发起人 / 管理看全部，其余看自己） |
| POST | `/activities/activities/{id}/submit/` | 已认证 | — | 征集投稿（一束文件 = 一个作品） |
| POST | `/activities/activities/{id}/review_submission/` | 登录 | 发起人或 `activities.review_collection` | 作品复审（录用 / 退稿） |
| POST | `/activities/activities/{id}/close/` | 登录 | 发起人或 `activities.manage_activity` | 提前关闭（众议 / 展示 / 调研结算；征集结束收件） |
| POST | `/activities/activities/{id}/add_exhibit/` | 登录 | 发起人或 `activities.manage_activity` | 加展品（待开始 / 展示中） |
| POST | `/activities/activities/{id}/update_exhibit/` | 登录 | 发起人或 `activities.manage_activity` | 改展品标题 / 换文件（仅待开始） |
| POST | `/activities/activities/{id}/delete_exhibit/` | 登录 | 发起人或 `activities.manage_activity` | 删展品（待开始 / 展示中） |
| POST | `/activities/activities/{id}/import_from_collection/` | 登录 | 发起人或 `activities.manage_activity` | 从征集导入作品为展品 |
| POST | `/activities/activities/{id}/rate/` | 已认证 | — | 展品点赞 / 点踩（三态） |
| POST | `/activities/activities/upload_image/` | 已认证 | — | 正文内嵌图片上传 |
| POST | `/activities/activities/survey_upload/` | 公开 | — | 问卷文件题上传（图片 / PDF） |

「认证」口径：公开 = `AllowAny`；登录 = 仅要求已登录（`IsAuthenticated`，未登录 403）；已认证 = 登录且账号已通过任一认证通道（`accounts.IsVerified`，未认证 403）。

## 端点详情

### 活动列表

`GET /activities/activities/`

**认证**：公开；**权限**：—。未登录时查询范围被收窄为「审核轴公开」且 `audience=public` 的调研与众议 / 展示；登录成员可见全部审核轴公开的活动。

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| type | string | 否 | `deliberation` / `collection` / `exhibition` / `survey` |
| status | string | 否 | `scheduled` / `open` / `closed` / `collecting` / `reviewing` / `archived` |
| creator | int | 否 | 发起人用户 id |
| search | string | 否 | 对 `title`、`body` 模糊搜索 |
| ordering | string | 否 | `created_at` / `updated_at` / `end_at`（前缀 `-` 倒序）。默认顺序：**未结束（进行中 / 待开始）在前、已结束（closed / archived）沉底**，同一档内按发布时间 `-created_at`（后发布的在上）；传 `ordering` 时以传入为准 |
| page | int | 否 | 页码，页大小 20（`PageNumberPagination`） |

**响应 `200 OK`**（列表序列化器，不含 `body`）

```json
{
  "count": 3, "next": null, "previous": null,
  "results": [
    {"id": 12, "type": "deliberation", "status": "open", "title": "运动会口号征集",
     "creator": {"id": 3, "username": "zhangsan", "nickname": "张三", "avatar": "/media/avatars/zs.png"},
     "audience": "members", "review_status": "approved", "owed": "vote",
     "start_at": null, "end_at": "2026-10-02T12:00:00+08:00", "is_permanent": false,
     "created_at": "2026-09-25T09:00:00+08:00", "updated_at": "2026-09-26T10:00:00+08:00"}
  ]
}
```

`creator` 复用全站 `SimpleUserSerializer`（`id` / `username` / `nickname` / `avatar`，`avatar` 可为 `null`；仅查看自己时额外带 `email`）。`review_status` 可为 `null`（尚无审核行）；`owed` 可为 `null`。

### 发起活动

`POST /activities/activities/`

**认证**：已认证；**权限**：—（`CanCreateActivity` 只判登录，实际门禁是 `IsVerified`）。请求体为 JSON。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| type | string | 是 | 四类型之一；非法值 400 |
| title | string | 是 | ≤200 字符 |
| body | string | 否 | 富文本 HTML，写入时消毒（与新闻同级） |
| start_at | datetime | 否 | 排期；未来时间则创建为 `scheduled`，到点自动开放 |
| end_at | datetime | 否 | 截止时间；缺省 = 起点 +3 天（众议）/ +7 天（其余）；须晚于 `start_at`。`is_permanent=true` 时必须省略或为 `null` |
| is_permanent | bool | 否 | 长期有效（不设截止）：默认 false。为 true 时 `end_at` 恒为 `null`、永不自动结算，只能手动 `close` |
| max_choices_per_voter | int | 否 | 众议：1..选项数；展示启用投票时 ≥1；默认 1 |
| is_secret_ballot | bool | 否 | 众议 / 展示投票：秘密票的个人明细仅超管可见；默认 false |
| option_texts | string[] | 众议必填 | 选项文本（≥2、≤50 个，写侧专用；读侧见 `options`） |
| allowed_extensions | string | 否 | 征集：允许后缀，逗号分隔（如 `".jpg,.png,.pdf"`），空 = 不限 |
| max_file_size | int | 否 | 征集：单文件字节上限；`null` = 按站点策略同步上传上限 |
| max_files_per_submission | int | 否 | 征集：单个作品文件数上限，默认 5 |
| max_submissions | int | 否 | 征集：最大作品数；`null` = 不限，设了则满额自动收口 |
| review_enabled | bool | 否 | 征集：默认 true；false = 提交即公开、跳过复审 |
| voting_enabled | bool | 否 | 展示：默认 false；true = 每展品绑定一个投票选项（创建后不可改） |
| audience | string | 否 | 受众：`public` / `members`，默认 `members`；调研=作答资格，众议 / 展示=投票资格（`public` 时未登录游客也可投，按设备标识判重）。创建后不可改；征集忽略此字段 |
| schema | object | 否 | 调研：SurveyJS Schema，须含 `pages`；非调研类型忽略。可在创建时一并提交（表单里的「设计问卷」弹层就是走这条路），也可创建后再 `PATCH` |
| comment_thread_status | string | 否 | 评论区状态 `open` / `muted` / `closed`，缺省 `open` |

创建后状态由后端计算：无排期 → 征集 `collecting`，其余 `open`；`start_at` 在未来 → `scheduled`。同时自动打开一条审核行（持 `reviews.force_publish` 或站点关闭内容审核时直接 `approved`，否则 `pending`）并建好评论区。

**响应 `201 Created`**：活动详情（字段见下节）。

**错误**

| 状态码 | 场景 |
|---|---|
| 403 | 未登录；或账号未认证（`IsVerified`） |
| 400 | 字段校验失败：`option_texts`「众议至少需要 2 个选项」「众议选项不超过 50 个」；`max_choices_per_voter`「每人最多选几项须在 1..选项数 之间」；`start_at`「开始时间须早于截止时间」；`end_at`「已勾选「长期有效」，不能再设截止时间」；`schema`「Schema 须包含 pages」 |

### 活动详情

`GET /activities/activities/{id}/`

**认证**：公开；**权限**：—。未登录只能取到 `audience=public` 的公开调研与众议 / 展示，其余一律 404；登录成员可取全部审核轴公开的活动、自己发起的活动，`reviews.moderate` 持有者可取全部。

**响应 `200 OK`**（详情序列化器，众议示例；其余类型差异见后）

```json
{
  "id": 12, "type": "deliberation", "status": "open",
  "title": "运动会口号征集", "body": "<p>投出你的一票</p>",
  "creator": {"id": 3, "username": "zhangsan", "nickname": "张三", "avatar": "/media/avatars/zs.png"},
  "review_status": "approved", "review_comment": "", "owed": "vote",
  "start_at": null, "end_at": "2026-10-02T12:00:00+08:00", "is_permanent": false,
  "max_choices_per_voter": 2, "is_secret_ballot": false,
  "allowed_extensions": "", "max_file_size": null,
  "max_files_per_submission": 5, "max_submissions": null,
  "review_enabled": true, "voting_enabled": false, "audience": "members",
  "schema": {"title": "", "pages": [{"name": "page1", "elements": []}]},
  "my_response": null, "response_count": null, "schema_editable": false,
  "options": [{"id": 31, "text": "团结拼搏", "order": 0, "vote_count": 4},
              {"id": 32, "text": "青春无畏", "order": 1, "vote_count": 2}],
  "ballots": [{"id": 7, "voter": {"id": 8, "username": "lisi", "nickname": "李四", "avatar": null}, "option_ids": [31], "created_at": "2026-09-26T10:00:00+08:00"}],
  "my_selections": [31], "total_ballots": 5,
  "my_submission": null, "submissions": null, "exhibits": null,
  "comment_thread": {"id": 22, "status": "open", "can_manage": true},
  "created_at": "2026-09-25T09:00:00+08:00", "updated_at": "2026-09-26T10:00:00+08:00"
}
```

字段语义（写侧专用字段 `option_texts`、`comment_thread_status` 不出现在响应中）：

- `review_comment`：审核评语，仅发起人或 `reviews.moderate` 持有者可见，其余为空串。
- `is_permanent`：长期活动标记（不设截止）。为 true 时 `end_at` 恒为 `null`，只能由发起人 / 管理员手动终结；为 false 时由 `end_at` 驱动自动结算。
- `options`：仅众议返回数组（`VoteOptionSerializer`：`id` / `text` / `order` / `vote_count`）；其余类型为 `null`。
- `ballots` / `my_selections` / `total_ballots`：无投票轴（非众议、或展示未启用投票）为 `null`；秘密投票下 `ballots` 仅超管可见（其余为 `null`）；`my_selections` 为当前身份已投的 option id 列表（登录按用户、访客按设备标识；未投 `null`）；公开受众下游客票的 `voter` 为 `null`。
- `my_submission` / `submissions`：仅征集返回。`my_submission` 是本人作品（无则 `null`）；`submissions` 复审者（发起人 / `activities.manage_activity` / `activities.review_collection`）见全部作品，其余登录成员只见 `review_status=accepted` 的作品；`review_enabled=false` 时全部作品公开。作品结构：`id` / `submitter` / `files`（附件：`id` / `file_url` / `file_type` / `file_name` / `file_size` / `uploaded_by` / `uploaded_at`）/ `review_status`（`pending` / `accepted` / `rejected`）/ `review_comment` / `reviewed_at` / `created_at`。
- `exhibits`：仅展示返回。展品结构：`id` / `title` / `files` / `vote_option_id`（未启用投票为 `null`）/ `vote_count` / `like_count` / `dislike_count` / `my_rating`（`like` / `dislike` / `null`）/ `created_at`。
- 调研：`audience`、`schema`、`my_response`（当前身份——登录用户或访客设备——的作答，未答 `null`）、`response_count`（作答总数，不作答列表）、`schema_editable`（问卷可否改，走生命周期判断）。非调研类型 `schema` 为默认空 Schema、后三者分别为 `null` / `null` / `false`。
- `comment_thread`：`id` / `status` / `can_manage`（当前用户能否管理该评论区）。

### 更新活动

`PUT /activities/activities/{id}/`　`PATCH /activities/activities/{id}/`

**认证**：登录；**权限**：发起人或 `activities.manage_activity`（对象级）。

**请求体**：可写字段与创建相同（`title` / `body` / `start_at` / `end_at` / `is_permanent` / 各类型配置 / `option_texts` / `schema` / `comment_thread_status`；序列化器未把 `type` 设为只读，但对变更类型无专门支持与校验）。

`is_permanent` 可在待开始期间切换：`true` 会清空既有 `end_at`（不传也清）；改回 `false` 必须同时给 `end_at`，否则 400（避免产生「非长期却无截止」的隐性永久）。

**门禁**（`views.perform_update` + `lifecycle`）

| 情形 | 结果 |
|---|---|
| 非 `scheduled` 改标题、正文、时间、`option_texts` 或配置 | 403 `{"detail": "活动开放后不可修改，仅待开始期间可改"}` |
| 调研 `schema`：`scheduled` 期间，或 `open` 且该问卷尚无作答 | 允许 |
| 调研 `schema`：其余状态 | 403 `{"detail": "当前不可修改问卷"}` |
| `audience` 与现值不同 | 400 `{"audience": "受众创建后不可改"}` |
| 空请求体且非 `scheduled`（未带 `comment_thread_status`） | 403（同第一条文案） |

`comment_thread_status` 单独提交时不要求 `scheduled`（切换评论区状态不是内容修改）。众议 `option_texts` 是整体替换，开放后选项锁定。

**响应 `200 OK`**：活动详情（同上节，字段随改动更新）。

### 删除活动

`DELETE /activities/activities/{id}/`

**认证**：登录；**权限**：发起人或 `activities.manage_activity`（对象级）。无状态门禁，任意状态可删。

**响应 `204 No Content`**（无响应体）。**删除调研活动不会删除其问卷与作答**（`Activity.questionnaire` 为 `SET_NULL`）：问卷变成无活动引用的孤儿行、历史作答完整保留，可在后台按「调研活动」为空识别并人工处置；加入单例问卷不挂活动，不受影响。

### 我发起的活动

`GET /activities/activities/mine/`

**认证**：登录；**权限**：—。返回当前用户发起的全部活动，**不受审核轴过滤**（待审 / 驳回 / 下架均可预览），与列表同为 `ActivityListSerializer` + 分页。

**查询参数**：同活动列表（`type` / `status` / `search` / `ordering` / `page` 等仍生效，结果已限定为本人）。

**响应 `200 OK`**：分页列表，条目结构同活动列表。

### 众议投票

`POST /activities/activities/{id}/vote/`

**认证**：`audience=public` 公开（`AllowAny`——游客与任何登录态均可投）；`audience=members` 须登录 + 已认证（未登录 401、未认证 403）。众议在 `open` 期间可投；展示只在 `voting_enabled=true` 且 `open` 时开放投票（`option_ids` 填展品对应的 `vote_option_id`）。

**请求体**：`{"option_ids": [31, 32], "turnstile_token": "..."}`——选项 id 数组：至少 1 项、不得重复、不得超过 `max_choices_per_voter`，且都须属于本活动。一人一张选票，投出后不可更改；全部已认证成员投完时众议自动结算（转 `closed`；公开受众下游客票不参与结算）。`turnstile_token` 仅在站点启用了 Turnstile 且请求来自未登录游客时必填（每次投票一个、单次有效）；成员投票不需要。

**判重与留痕**：登录用户按账号一人一张；`audience=public` 的游客按 `X-Device-Id` 头（UUID）一设备一张，未带合法标识返回 400；游客票记录 IP（取 `X-Forwarded-For` 末段，即 Nginx 追加的真实来源）与设备标识备查。设备号由客户端生成、可轮换，因此游客票另按 **（IP + 活动）每小时 N 票**限流兜底（`SiteSettings.public_vote_per_ip_per_hour`，默认 120）；超出返回 `429`。

**响应 `200 OK`**：活动详情（`options[].vote_count`、`ballots`、`my_selections`、`total_ballots` 随票数更新；游客的 `my_selections` 按设备标识回显）。

**错误**（均为 400 + `{"detail": "…"}`，另有 401 / 403 见上）：类型非众议 / 展示 → `仅众议/展示可以投票`；展示未启用投票 → `该展示未启用投票`；非 `open` → `投票已结束`；已投过票 → `你已经投过票了，不能修改`（游客重复 → `该设备已投过票，不能重复投票`）；游客缺设备标识 → `缺少设备标识`；未选或非数组 → `请至少选择一个选项`；重复选项 → `不能重复选择同一选项`；超过 K 值 → `最多选择 {max_choices_per_voter} 项`；选项非法 → `无效的选项` / `存在不属于本活动的选项`。

### 调研作答

`POST /activities/activities/{id}/respond/`

**认证**：公开（`AllowAny`）；**权限**：—。`audience=public` 任何人可答，`audience=members` 仅登录成员；活动须 `open`，审核轴须为 `approved` 或无审核行（否则 400「调研尚未公开」）。已登录用户每份调研一次；访客按 `X-Device-Id` 头（UUID）一次，未带合法标识返回 400。

**请求体**：`{"answers": {"grade": "高一", "intro": "你好"}}`——`answers` 须为 JSON 对象（问卷题目的 `name` → 作答值）。

**响应 `201 Created`**：活动详情（`my_response` 为本次作答）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 调研尚未公开；仅调研可以作答；当前不可作答（非 `open`）；`answers 须为 JSON 对象`；缺少设备标识；你已经提交过了 |
| 401 | `仅成员可作答，请先登录`——仅成员受众且未登录时的防御分支；访客的可见范围本身已排除仅成员调研，实际先返回 404 |
| 404 | 访客访问非「公开受众的公开调研」的活动 |

### 问卷作答查看

`GET /activities/activities/{id}/responses/`

**认证**：登录；**权限**：—。发起人或持 `activities.manage_activity` 者看全部作答（`is_manager=true`）；其他登录用户只看自己的；未登录 403；非调研活动 400。

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| q | string | 否 | 检索作答内容（模糊、大小写不敏感、全角半角等价）。只匹配用户填写的值，不匹配作答者身份与提交时间；选择题按**选项展示文本**匹配（存 `news` 也能用「新闻」搜到），文件题匹配文件名与链接。空串 / 纯空白 = 不检索。长度上限 100 字符 |

**响应 `200 OK`**（整列返回，无分页；按提交时间倒序）

```json
{
  "schema": {"title": "", "pages": [{"name": "page1", "elements": []}]},
  "is_manager": true,
  "total": 2,
  "query": "摄影",
  "results": [
    {"id": 5, "user_label": "zhangsan", "answers": {"grade": "高一", "intro": "你好"},
     "submitted_at": "2026-09-26T10:00:00+08:00",
     "matches": [{"name": "intro", "title": "自我介绍", "snippet": "…喜欢摄影和剪辑…"}]},
    {"id": 6, "user_label": "访客 · 1a2b3c4d", "answers": {"grade": "高二"},
     "submitted_at": "2026-09-26T11:00:00+08:00", "matches": []}
  ]
}
```

`schema` 为该调研的问卷 Schema；`user_label`：登录用户为 `username`，访客为 `访客 · {设备标识前 8 位}`（无标识则「访客」）。
`total` 是**未过滤**的可见份数（检索时用于显示「匹配 N / 共 M」）；`query` 回显生效的检索词（空串 = 未检索）；
`matches` 是命中字段（最多 3 条，含题目标题与前后文片段），未检索或未命中时为空数组。

**错误**

| 状态码 | 场景 |
|---|---|
| 403 | 未登录 |
| 400 | 仅调研有问卷作答；问卷不存在 |
| 404 | 活动不可见（审核轴 / 不存在） |

### 征集投稿

`POST /activities/activities/{id}/submit/`

**认证**：已认证；**权限**：—。仅征集且 `collecting` 期间可投；一人一作品、提交即锁定（不可改 / 撤）。请求为 `multipart/form-data`，字段 `files`（file[]，必填，一个作品的整束文件，数量 ≤ `max_files_per_submission`）。

每个文件依次通过：全局上传校验（站点同步上传上限、全局禁用扩展名）→ 活动级校验（`max_file_size` 单文件字节上限、`allowed_extensions` 后缀白名单）。作品数达 `max_submissions` 时自动收件结束（`collecting` → `reviewing` / `archived`）。

**响应 `201 Created`**：活动详情（`my_submission` 为新作品，`submissions` 随可见性更新）。

**错误**（400 + `{"detail": "…"}`）：类型非征集 → `仅征集可以投稿`；非 `collecting` → `征集已结束收件` / `当前不可投稿`；已提交过 → `你已经提交过作品了（一人一作品）`；未带文件 → `请至少上传一个文件`；文件数超限 → `单个作品最多 {max_files_per_submission} 个文件`；全局校验失败 → `文件大小不能超过 {站点上限}` / `禁止上传此类型的文件`；超单文件上限 → `文件「{name}」超过征集规定的单文件大小上限`；后缀不合法 → `文件「{name}」的后缀不在允许范围`。

### 征集复审（录用 / 退稿）

`POST /activities/activities/{id}/review_submission/`

**认证**：登录；**权限**：发起人或 `activities.review_collection`（对象级）。仅征集、且 `review_enabled=true`、状态为 `collecting` 或 `reviewing`（两阶段均可滚动复审）。

**请求体**：`{"submission_id": 4, "decision": "accepted", "comment": "构图不错"}`——`decision` 必须是 `accepted`（录用）或 `rejected`（退稿）；`comment` 为评语（可空）。

**响应 `200 OK`**：活动详情（对应作品的 `review_status` / `review_comment` / `reviewed_at` 更新；录用作品进入公开的 `submissions`）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 仅征集作品可复审；本征集未启用复审；当前不可复审；decision 须为 accepted 或 rejected |
| 404 | 作品不存在（`submission_id` 缺省 / 非法 / 非本活动） |

### 提前关闭

`POST /activities/activities/{id}/close/`

**认证**：登录；**权限**：发起人或 `activities.manage_activity`（对象级）。无请求体。众议 / 展示 / 调研须 `open`，转 `closed`（立即结算）；征集须 `collecting`，转 `reviewing`（`review_enabled=true`）或 `archived`（跳过复审）。

**响应 `200 OK`**：活动详情（`status` 已更新）。

**错误**：400 `{"detail": "当前不可关闭"}`——非发起人 / 非 `activities.manage_activity`，或状态不允许关闭。

### 加展品

`POST /activities/activities/{id}/add_exhibit/`

**认证**：登录；**权限**：发起人或 `activities.manage_activity`（对象级）。仅展示，状态为 `scheduled` 或 `open`（待开始 / 展示中均可加）。请求为 `multipart/form-data`：`title`（string，选填，启用投票时同步为选项文本）+ `files`（file[]，至少 1 个，逐个过全局上传校验）。

启用投票（`voting_enabled=true`）的展示会为每个展品自动创建一个绑定的 `VoteOption`（票数即该选项票数）。

**响应 `200 OK`**：活动详情（`exhibits` 含新展品）。

**错误**（`{"detail": "…"}`）：400 `仅展示可在待开始/展示中加展品`（类型 / 状态不符）、400 `展品至少需要 1 个文件`、400 全局上传校验文案。

### 改展品

`POST /activities/activities/{id}/update_exhibit/`

**认证**：登录；**权限**：发起人或 `activities.manage_activity`（对象级）。仅展示且 **仅 `scheduled`**（开放后展品锁定）。请求为 `multipart/form-data`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| exhibit_id | int | 是 | 目标展品 |
| title | string | 否 | 给了就改（同步更新绑定选项文本） |
| files | file[] | 否 | 给了就整体替换该展品的全部文件 |

**响应 `200 OK`**：活动详情。

**错误**：400 `仅展示可在待开始期改展品`（类型 / 状态不符）；404 `展品不存在`；400 上传校验文案。

### 删展品

`POST /activities/activities/{id}/delete_exhibit/`

**认证**：登录；**权限**：发起人或 `activities.manage_activity`（对象级）。仅展示，`scheduled` / `open` 期间可删（`closed` 后不可再动）。请求体 `{"exhibit_id": 7}`；连带删除绑定的投票选项与附件。

**响应 `200 OK`**：活动详情。**错误**：400 `仅展示可在待开始/展示中删展品`；404 `展品不存在`。

### 从征集导入展品

`POST /activities/activities/{id}/import_from_collection/`

**认证**：登录；**权限**：发起人或 `activities.manage_activity`（对象级）。仅展示，`scheduled` / `open` 期间可用。请求体 `{"collection_id": 9, "submission_ids": [4, 5]}`——把征集里勾选的作品复制为独立展品快照（附件走复制，不影响原作品）。

**响应 `200 OK`**：活动详情（`exhibits` 含导入的展品）。

**错误**：400 `仅展示可在待开始/展示中导入展品`；404 `征集不存在`（id 非法 / 目标非征集）；400 `未选择任何作品`。

### 展品点赞 / 点踩

`POST /activities/activities/{id}/rate/`

**认证**：已认证；**权限**：—。仅展示且 `open` 期间可评分。请求体 `{"exhibit_id": 7, "choice": "like"}`；`choice` 为 `like` / `dislike`。三态：`none`（无记录）/ `like` / `dislike`——再点当前态即取消，换选即翻转；每人每展品一行，记名。

**响应 `200 OK`**：活动详情（对应展品的 `like_count` / `dislike_count` / `my_rating` 更新）。

**错误**：400 `当前不可评分（展示未开放或已结束）`；400 `choice 须为 like 或 dislike`；404 `展品不存在`（`exhibit_id` 缺省 / 非法 / 非本活动）。

### 正文图片上传

`POST /activities/activities/upload_image/`

**认证**：已认证；**权限**：—。供富文本编辑器「插入图片」与 Word 导入共用，请求为 `multipart/form-data`，字段 `image`（必填，≤5MB，仅 `image/jpeg`、`image/png`、`image/gif`、`image/webp`）。

**响应 `200 OK`**

```json
{"url": "http://localhost:8000/media/activity_content_images/3f2a1c9d8e7b4a5f.png"}
```

**错误**（400 + `{"detail": "…"}`）：`请选择图片。` / `图片不能超过 5MB。` / `仅支持 JPG、PNG、GIF、WebP 格式。`

### 问卷文件题上传

`POST /activities/activities/survey_upload/`

**认证**：公开（问卷填答者含未登录游客）；**权限**：—。请求为 `multipart/form-data`，字段 `file`（必填，≤ 站点策略同步上传上限，仅 `image/jpeg`、`image/png`、`image/gif`、`image/webp`、`application/pdf`）。

**响应 `200 OK`**

```json
{"url": "http://localhost:8000/media/survey_uploads/3f2a1c9d8e7b4a5f.png"}
```

**错误**（400 + `{"detail": "…"}`）：`请选择文件。` / `文件大小不能超过 …` / `仅支持图片（JPG / PNG / GIF / WebP）或 PDF。`

> 问卷填写时由 SurveyJS 的 `onUploadFiles` 事件调用（前端 `utils/survey.ts`）；上传成功后 URL 存入作答（`[{name, content}]`），避免 SurveyJS 默认把文件传到海外服务。
