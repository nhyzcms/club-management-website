# 明信片互寄 API（`events` 形态模块）

明信片互寄是 `events` app 的首个**形态模块**（`events/modules/postcard/`），对外路由挂在 `/events/postcard/` 下。通用「活动」CRUD（`EventViewSet` 与 `/#/events` 页面）已于 2026-11 下线：现在 `Event` 只作为本模块的**壳**（标题 / 简介 / 正文 / 时间窗 / 状态 / 可见性 / `module_key="postcard"`），不再提供独立的 `/events/` 列表与详情接口。

> 全局约定（认证 / CSRF / 分页 / 错误）见 [API 总览](README.md)。用户与运营视角的流程说明见 [明信片互寄指南](../guides/postcard.md)；需求与实现决策见 [实施方案](../plans/postcard-exchange.md)。

## 阶段（phase）与门禁

阶段不是存储字段，而是按时间**惰性推导**（`events/modules/postcard/state.py`）；管理员改节点时间即改阶段，无定时任务：

```text
未开始 ──start_at──> 登记中 ──ship_at──> 已寄出 ──distribute_at──> 下发中 ──end_at──> 已结束
```

- `ship_at` / `distribute_at` 可空 = 跳过该阶段；
- `Event.status=draft` → 未开始；`archived` → 已结束；
- **仅「登记中」开放登记**（`can_register`），其余阶段用户侧只读公告与进度条；
- 每次请求先 `lifecycle.touch()` 推进 Event 壳层状态；阶段推导为「已结束」时顺带触发照片文件全量清理（幂等）。

「当前活动」= 最新一个 `module_key="postcard"` 的 Event（优先未归档、`start_at` 最新）；未发布草稿对公开端不可见，管理端可见。

## 登记数据形状

### 登记单（`PostcardRegistration`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `reg_code` | string | 6 位登记码；**同一发件人（姓名 + 年级 + 班级）在活动内共用**。未达发放条件时返回掩码（前 2 位 + `****`） |
| `code_granted` | bool | 是否已到发码时机 |
| `sender_name` | string | 寄出人姓名（≤64） |
| `grade` / `grade_label` | string | `g1` / `g2` / `g3` → 高一 / 高二 / 高三 |
| `class_no` | int | 班级 1–8 |
| `dest_region` / `dest_school` | string | 寄达区（固定 16 区之一）/ 寄达校（须在配置清单内且区校配对） |
| `status` / `status_label` | string | `registered` / `reported` / `cancelled` → 已登记 / 已报寄 / 已取消 |
| `created_at` / `updated_at` | datetime | |
| `items` | array | 每张明信片一项（见下） |

### 条目（`PostcardItem`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 条目 id |
| `barcode` | string | 7 位条码（一码一明信片） |
| `status` / `status_label` | string | 同登记单三态 |
| `review_state` / `review_label` | string / null | `pending` / `ai_passed` / `ai_failed` / `manual_pending` / `manual_passed` / `manual_failed` |
| `mismatched` | array | AI 判定的不匹配项（给用户看「哪里填错」） |
| `comment` | string | AI 评语 |
| `photos` | array | `[{id, side}]`，`side` ∈ `front` / `back`；取图走 `photo/<id>/` |

### 登记码发放规则（服务端权威）

- 存在失败条目（`ai_failed` / `manual_failed`）→ **不发码**（返回 `null` + 掩码摘要）；
- 已转人工复核（`manual_pending`）→ **立即发码**（不等人工结果）；
- 全部通过（AI / 人工）→ 发码；
- 仍在 AI 审核（`pending`）→ 不发码，但登记接口返回一次性 `access_token` 供轮询。

## 公开端点

| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| GET | `/events/postcard/portal/` | 公开 | 独立页一站式状态（阶段 / 公告 / 表单选项） |
| POST | `/events/postcard/register/` | 公开 | 登记提交（multipart，含照片） |
| GET | `/events/postcard/my/` | 公开 | 历史登记记录（按设备 / 指纹 / 登录用户归集） |
| POST | `/events/postcard/lookup/` | 公开 | 按登记码或姓名查询 |
| GET / PATCH / POST | `/events/postcard/my/<reg_code>/` | 公开 | 查看 / 修改 / 取消（登记码即能力凭证） |
| POST | `/events/postcard/my/<reg_code>/review-request/` | 公开 | 申请人工复核 |
| POST | `/events/postcard/my/<reg_code>/purge-photos/` | 公开 | 清理失败照片（`sendBeacon`） |
| GET / POST | `/events/postcard/my/token/<token>/…` | 公开 | 审核中轮询：状态 / 申请复核 / 清照片 |
| POST | `/events/postcard/suggestions/` | 公开 | 活动建议箱 |
| GET | `/events/postcard/announcement-pdf/` | 公开 | 公告 PDF（`CSP: sandbox`） |
| GET | `/events/postcard/photo/<pk>/` | 公开* | 照片下发（复核权限或 `?reg_code=` 匹配） |

\* 照片端点对匿名开放，但必须满足「持 `events.review_postcard` / `events.manage_postcard` / 超管」或「URL 携带本条的 6 位登记码」；否则 403。

公开写端点按 **IP + 设备**双轨限流（设备标识取 `club_device` cookie，缺省退回 IP）：

| 端点 | IP 轨 | 设备轨 |
|---|---|---|
| 登记 `register/` | 60 / 时 | 10 / 时 |
| 建议 `suggestions/` | 5 / 时 | 5 / 时 |
| 查询 `lookup/` | 300 / 时 | 20 / 分 |
| 凭证端点 `my/<code>/…` / `my/token/…` | 120 / 时 | 30 / 分 |

### 门户状态

`GET /events/postcard/portal/`

返回当前阶段与页面所需元数据。**未开始时对普通用户不泄露年级 / 学校清单**；「登记中」对所有人生效，管理员任何阶段可见，历史记录修改场景在活动开始后仍下发清单。

**响应 `200 OK`**

```json
{
  "phase": "registering",
  "phase_label": "登记中",
  "can_register": true,
  "is_admin": false,
  "sample_ready": true,
  "event": {"id": 12, "title": "明信片互寄 2026", "summary": "…", "start_at": "…", "end_at": "…"},
  "progress": [{"key": "start", "label": "登记开始", "time": "…", "reached": true}],
  "grades": [{"value": "g1", "label": "高一"}],
  "classes": [1, 2, 3, 4, 5, 6, 7, 8],
  "regions": ["浦东新区", "宝山区", "…"],
  "schools": [{"region": "浦东新区", "name": "××中学", "no": 1}],
  "announcement_pdf": false,
  "announcement_body": "<p>…</p>"
}
```

`announcement_body` 入库前已经 `sanitize_html` 白名单净化，前端可直接渲染。从未配置活动时 `event` 为 `null`、`grades` / `regions` / `schools` 为空。

### 登记提交

`POST /events/postcard/register/`

**认证**：公开；**权限**：—，但受阶段门禁、样例门禁、Turnstile 与双轨限流约束。

**请求体**：`multipart/form-data`（文件与 JSON 字符串混合）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sender_name` | string | 是 | ≤64 |
| `grade` | string | 是 | `g1` / `g2` / `g3`，且须在活动允许年级内 |
| `class_no` | int | 是 | 1–8 |
| `dest_region` | string | 是 | 上海市固定 16 区之一 |
| `dest_school` | string | 是 | 须与 `dest_region` 在配置清单中配对命中 |
| `items` | string(JSON) | 是 | `[{"barcode":"1234567"}]`，1–5 项、条码不得重复 |
| `photo_<i>_front` / `photo_<i>_back` | file | 是 | 第 `i` 张（从 0 起）的正 / 反面照片，两面都必填 |
| `fingerprint` | string | 否 | 轻量 JS 指纹（8–128 位小写十六进制）；格式不对静默降级为仅 Cookie 识别 |
| `turnstile_token` | string | 条件 | 站点启用 Turnstile 时必填 |

**服务端校验顺序**：阶段 → 样例配置 → Turnstile → 字段校验 → 年级 / 区校清单 → 条码存在且未被占用 → 照片逐张重编码（任何一张失败整单拒绝、零残留）→ 原子建单。

**照片约束**：原文件 ≤5MB；服务端按真实图片解码（魔数 + Pillow `verify`），拒绝解码炸弹（>8000px 或 >4000 万像素）；统一缩放到最长边 1280、JPEG 质量 80、剥离 EXIF，落**私有存储**。

**响应 `201 Created`**

```json
{
  "reg_code": "123456",
  "code_granted": true,
  "access_token": "32 位十六进制",
  "message": "登记成功！请保存好您的登记码，凭它可查看和修改自己的登记记录",
  "registration": {"…": "登记单摘要（见上）"},
  "review": {"state": "pending", "hint": "照片正在 AI 审核，结果稍后可在「历史登记记录」查看"}
}
```

`reg_code` 未到发放时机时为 `null`（`code_granted=false`），同时一律返回 `access_token`（只读轮询凭证，不能改 / 取消 / 取图）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 不在登记期 / 填写样例未配置 / 字段或清单不合法 / 条码不存在或已被登记 / 照片缺失或不合格 / 人机验证未通过 |
| 429 | 触发 IP 或设备限流 |

### 历史登记记录

`GET /events/postcard/my/?fingerprint=<hash>`

**认证**：公开。按 `club_device` 设备号 + 指纹哈希 + 登录用户三轨并集归集当前活动下的登记单，`-created_at` 排序。返回 `{"results": [...]}`（不分页）；每条附 `access_token` 供本人轮询。

### 查询（登记码 / 姓名）

`POST /events/postcard/lookup/`

**请求体**：`{"q": "123456"}` 或 `{"q": "张三"}`

- `q` 为 6 位数字 → 登记码即能力凭证，返回**完整**摘要（含真码与照片 id）；
- `q` 为姓名（2–64 字、**精确匹配**，最多 20 条）→ 只返回**掩码**摘要（`82****`，照片列表清空）；
- 姓名不命中返回空列表，不区分「无此人」与「无记录」。

**响应 `200 OK`**：`{"kind": "code"|"name", "results": [...]}`。**错误**：400 空查询 / 姓名过短或过长；429 限流。

### 查看 / 修改 / 取消

`GET /events/postcard/my/<reg_code>/?id=<submission_id>`

同一登记码可能对应多份提交：`id` 指定单份，缺省取最早一份（修改时若多份且未指定 `id`，返回 400）。码不命中一律 404，不泄露存在性。

`PATCH /events/postcard/my/<reg_code>/?id=<submission_id>`

仅可改寄出人信息：`sender_name` / `grade` / `class_no` / `dest_region` / `dest_school`（条码与照片不可改——实物已印好）。校验与登记同一套清单规则。已取消的登记不能修改（400）。

`POST /events/postcard/my/<reg_code>/`

取消登记：`{"scope": "one"}`（默认，仅当前单份）或 `{"scope": "all"}`（该码下全部提交，不可逆；前端须二次确认）。登记单与全部条目置 `cancelled`；响应为登记摘要 + `cancelled_count`。

### 申请人工复核 / 清理照片

`POST /events/postcard/my/<reg_code>/review-request/`

把该登记码下全部 `ai_failed` 条目整批转为 `manual_pending`，并给持 `events.review_postcard`（及 `events.manage_postcard`）的管理员发站内信（同一登记码的未读通知聚合为一条）。无 `ai_failed` 条目时 400。

`POST /events/postcard/my/<reg_code>/purge-photos/`

用户关闭标签页时由 `sendBeacon` 调用（豁免 CSRF，仅凭登记码）：删除该码下**终态失败**照片文件，幂等；响应 `{"purged": n}`。

轮询凭证版：`GET /events/postcard/my/token/<token>/`（只读摘要）、`POST …/review-request/`、`POST …/purge-photos/`。凭证不能改 / 取消 / 取图。

### 建议箱

`POST /events/postcard/suggestions/`

**请求体**：`{"content": "≤1000 字", "contact": "可选 ≤128", "turnstile_token": "…"}`。活动未配置 400；Turnstile 必过；限流 5/时（IP + 设备）。**响应 `201`**：`{"message": "感谢你的建议！"}`。

### 公告 PDF

`GET /events/postcard/announcement-pdf/`

返回私有存储中的公告 PDF：`Content-Type: application/pdf`、`Content-Disposition: inline`、`X-Content-Type-Options: nosniff`、`Content-Security-Policy: sandbox`。文件不存在 404。

### 照片

`GET /events/postcard/photo/<pk>/?reg_code=<6 位>`

固定 `image/jpeg` + `nosniff` + `Cache-Control: private, max-age=60`。审核人员（复核 / 管理 / 超管）可直接取；普通用户必须携带本条登记单的 6 位码。无权 403，文件不存在 404。

## 管理端点

所有管理端点挂在 `/events/postcard/admin/`，要求登录且持命名权限：

- `events.manage_postcard`：配置 / 条码 / 记录 / 导出 / 统计 / 建议 / 审计 / AI 配置与样例 / 海报导入；
- `events.review_postcard`：复核台 + 签收查询 / 确认 / 回退（`manage_postcard` 隐含复核权）。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET / PUT | `admin/config/` | manage | 读 / 写活动配置（首次保存自动建 Event 壳） |
| POST | `admin/publish/` | manage | 发布草稿（`draft` → `scheduled` / `active`） |
| POST | `admin/archive/` | manage | 归档当前活动 |
| POST | `admin/new-season/` | manage | 归档当前并新建下一届草稿（复制年级 / 学校清单；AI 配置继承、API Key 清空） |
| GET / POST | `admin/barcodes/` | manage | 条码汇总 / 生成（可覆盖重建） |
| GET | `admin/barcodes/pdf/` | manage | 整版条码 PDF |
| GET | `admin/records/` | manage | 登记条目列表（分页 + 搜索筛选） |
| GET | `admin/export/?fmt=xlsx\|pdf` | manage | 导出记录 |
| GET | `admin/stats/` | manage | 统计汇总 |
| PATCH / DELETE | `admin/registrations/<reg_code>/` | manage | 按登记码改 / 删（多份提交时 400） |
| PATCH / DELETE | `admin/registrations/by-id/<pk>/` | manage | 按单份提交改 / 删 |
| GET | `admin/suggestions/` | manage | 建议列表（分页） |
| GET | `admin/audit/` | manage | 审计日志（分页、只读） |
| GET / PUT | `admin/ai/config/` | manage | AI 审核配置（`api_key` 写后不可读） |
| POST | `admin/ai/test/` | manage | 用当前填写的草稿参数发一次最小请求（不落库；60/时） |
| POST | `admin/ai/models/` | manage | 代理服务商 `{base_url}/models` 的模型清单（120/时） |
| POST | `admin/ai/explain/` | manage | 一次性样例解读（不落库，10/时） |
| POST | `admin/ai/preview/` | manage | 模拟环境真调一次审核判定（不落库 / 不存照片 / 不写审计，120/时） |
| GET / POST | `admin/ai/samples/` | manage | 样例列表 / 上传 |
| DELETE | `admin/ai/samples/<pk>/` | manage | 删除样例 |
| POST | `admin/ai/samples/<pk>/explain/` | manage | 让 AI 复述对样例的理解 |
| GET | `admin/ai/samples/<pk>/image/` | review | 样例照片下发 |
| POST | `admin/schools/import/` | manage | 海报 AI 识别寄达校（只回结果、不落库，10/时） |
| GET | `admin/review/` | review | 复核队列（`state=manual_pending\|ai_failed\|空`） |
| POST | `admin/review/<item_pk>/` | review | 人工复核判定 `pass` / `fail` |
| GET | `admin/lookup/?barcode=1234567` | review | 签收查询 |
| POST | `admin/confirm/` | review | 签收确认（置「已报寄」，幂等） |
| POST | `admin/unreport/` | review | 误签回退（已报寄 → 已登记） |

### 活动配置

`GET /events/postcard/admin/config/` → 未配置时 `{"configured": false, "phase": "not_started"}`；已配置返回：

```json
{
  "configured": true,
  "phase": "registering",
  "phase_label": "登记中",
  "event": {"id": 12, "title": "…", "summary": "…", "status": "active", "start_at": "…", "end_at": "…"},
  "announcement_body": "<p>…</p>",
  "has_announcement_pdf": true,
  "allowed_grades": ["g1", "g2"],
  "destination_schools": [{"region": "浦东新区", "name": "××中学", "no": 1}],
  "ship_at": null,
  "distribute_at": null,
  "barcode_count": 6000,
  "registration_count": 128
}
```

`PUT /events/postcard/admin/config/` 接受 `multipart/form-data` 或 JSON：

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` / `start_at` / `end_at` | 是 | Event 壳字段；`end_at` 必须晚于 `start_at` |
| `summary` / `body` | 否 | `body` 为公告正文 HTML，服务端 `sanitize_html` |
| `ship_at` / `distribute_at` | 否 | 可空；须落在 `[start_at, end_at]` 内且顺序正确 |
| `allowed_grades` | 否 | `g1` / `g2` / `g3` 子集；空 = 全部 |
| `destination_schools` | 否 | `[{region, name, no?}]`；`region` 须为固定 16 区之一，`no` 为 1–9999 整数 |
| `announcement_pdf` | 否 | 仅 PDF（`%PDF-` 魔数）、≤10MB |
| `clear_announcement_pdf` | 否 | `1` / `true` 清除已有 PDF |

- 壳字段（标题 / 简介 / 起止时间）在 `active` 后锁定；节点、学校清单与公告在活动期间**随时可改**。
- `destination_schools` 在 HTML 表单里以 JSON 字符串提交（`JSONListField` 解码），JSON 请求照常传数组。
- 首次 `PUT` 自动创建 `module_key="postcard"`、`visibility=public`、`status=draft` 的 Event 壳。
- 所有写操作落 `PostcardAuditLog`。

### 发布 / 归档 / 多届

- `POST admin/publish/`：仅 `draft` 可发布；`start_at` 在未来 → `scheduled`，否则 → `active`。
- `POST admin/archive/`：把当前活动置 `archived`（数据保留、可查）；已归档 400。
- `POST admin/new-season/`：归档当前活动（若未归档）+ 新建草稿活动（标题 `明信片互寄 <年份>`，`start_at=now+7d`、`end_at=now+37d`），复制上一届的年级与寄达校清单；**AI 配置为全局单例，新一届自动继承上一年度的参数，但 `api_key` 会清空**（需管理员重新填写；审计 `new_season` 记录 `api_key_cleared`）。响应 `{event_id, previous_event, status}`（201）。

### 条码

`GET admin/barcodes/` → `{total, bound, min, max, step, default}`（1500 / 10000 / 500 / 6000）。

`POST admin/barcodes/` → `{"count": 6000, "replace": false}`

- `count` 须为 1500–10000 且是 500 的倍数；单活动累计 ≤10000；
- 默认增量追加；`replace=true` **覆盖重建**：只清「未被登记占用」的条码，存在已占用条码时 400 拒绝；
- 响应 `{generated, total, replaced}`（201），落审计。

`GET admin/barcodes/pdf/` → A4 整版 PDF：条码 40×20mm、间隙 2mm、每页 5 列 × 13 行 = 65 枚，流式输出。

### 记录 / 导出 / 统计

`GET admin/records/`：按**条目**平铺（登记单信息随行），分页 20/页。查询参数：`q`（姓名 / 登记码 / 条码模糊）、`status`（登记单状态）、`item_status`、`grade`、`class_no`、`school`、`region`。

`GET admin/export/?fmt=xlsx|pdf`：参数与记录列表一致；`fmt` 只认 `xlsx` / `pdf`（不要用 `format`，会被 DRF 内容协商拦截）。CSV 风格公式注入防护同全站导出（`= + - @` 开头前置 `'`）。

`GET admin/stats/`：

```json
{
  "registrations": {"total": 0, "registered": 0, "reported": 0, "cancelled": 0},
  "items": {"total": 0, "registered": 0, "reported": 0, "cancelled": 0},
  "destination_schools": 0,
  "by_school": [{"school": "××中学", "total": 0, "reported": 0}],
  "by_grade": [{"grade": "g1", "total": 0}],
  "by_day": [{"day": "2026-11-08", "total": 0}]
}
```

统计口径：**已取消条目不计入** `items.total` 与按校 / 按年级 / 按日分布；`items.cancelled` 单独给出。

### 登记单改 / 删

`PATCH admin/registrations/by-id/<pk>/`：改 `sender_name` / `grade` / `class_no` / `dest_region` / `dest_school` / `status`。`status=cancelled` 会联动全部条目取消。

`DELETE`：删除登记单（级联条目）并删除照片文件，落审计。

按 `reg_code` 的路由在**同一码对应多份提交**时返回 400，要求改用 `by-id`——避免误伤整批。

### 签收

- `GET admin/lookup/?barcode=<7 位>`：命中返回条目状态 + 完整登记摘要；未命中 `404 {"detail": "明信片未登记，请先登记！"}`；条码格式错 400。
- `POST admin/confirm/`：`{"barcode": "1234567"}` → 条目置 `reported`，登记单按「全部有效条目已报寄」联动；重复确认幂等（`already_reported=true`）；已取消登记 400。
- `POST admin/unreport/`：`{"barcode": "…"}` → 已报寄回退为 `registered` 并联动登记单。

### AI 审核配置

`GET admin/ai/config/` 只回 `{configured, enabled, ready, base_url, model, extra_headers, timeout_seconds, ip_blacklist, prompt_prefix, api_key_set}`——**`api_key` 永不回显**。`ready` = 启用 + `base_url` + `model` 齐备（部分兼容服务可免鉴权）。字段 `model` 在界面上叫「模型 ID」。

`PUT admin/ai/config/`：`base_url`（http/https）、`api_key`（留空 = 保持原值）、`model`、`extra_headers`（字符串键值对）、`timeout_seconds`（5–120，默认 20）、`ip_blacklist`（动漫形象黑名单）、`prompt_prefix`（前置提示词，≤4000 字，可多行；空 = 不附加）、`enabled`。`prompt_prefix` 会并入每次请求的首条 system 消息——审图 / 样例解读 / 海报识别 / 测试连接统一生效；审计只记长度（`prompt_prefix_len`），不落正文。

`POST admin/ai/test/`：用**当前填写的草稿参数**（请求体可选覆盖 `base_url` / `model` / `api_key` / `extra_headers` / `timeout_seconds`，缺省回落到已保存配置；**只在本次请求生效，不落库**）发一次最小对话请求，返回 `{ok, latency_ms, model, reply}` 或 `{ok: false, error}`（HTTP 200，按 `ok` 展示；不回显密钥）。限 60 次/时。再带 `dry_run: true` 时**跳过审计**（模拟环境用，`#/postcard/admin?sim=1`）。前端「测试连接」与「获取模型列表」同口径，都提交当前表单。

`POST admin/ai/models/`：代理服务商 `GET {base_url}/models`，可选带本次填写的 `base_url` / `api_key` / `extra_headers` / `timeout_seconds` 覆盖参数（**正式端与模拟环境同口径，不落库**）。只回 `{ok: true, models: ["…"]}` 或 `{ok: false, error}`；响应上限 512 KiB、模型 ID 经白名单校验；服务商无 `/models`（404）时提示手填模型 ID。**不内置写死清单**。限 120 次/时。

审核管线：OpenAI 兼容 `/chat/completions`（urllib 实现，零 SDK），输入用户照片 + 管理员样例 + 规则 + 黑名单；输出严格 JSON（`matched` / `mismatched_items` / `blacklist_hit` / `blacklist_names` / `comment`）。最多 6 次调用机会、指数退避；全败转人工复核。连续 5 个用户失败会邮件告警所有绑定邮箱的管理员。

### 样例与海报导入

- `GET admin/ai/samples/` → `{results: [{id, caption, has_image, created_at}], sample_ready}`；**活动至少一条样例才开放登记**。
- `POST admin/ai/samples/`：`multipart`（`image` + `caption`），照片走与用户照片同一道安全管线。
- `POST admin/ai/samples/<pk>/explain/`：让 AI 复述它对样例的理解（核对 AI 是否理解正确）；未启用 / 调用失败给人话错误。
- `POST admin/ai/explain/`：**一次性**解读（模拟环境用）——`multipart`（`image` + `caption`），走同一套照片安全管线，复用上面的 prompt；**不落库、不留文件、不写审计**，返回 `{text}`。
- `POST admin/schools/import/`：上传活动海报 → AI 识别参与学校、所在区与区内编号；**只回结果、不落库**，前端合并进配置表单、管理员核对后保存才生效。响应含 `schools` / `skipped` / `missing_no`；AI 未配置返回 `400 {code: "ai_not_configured"}`。

### 模拟环境专用

- `POST admin/ai/preview/`：**只给模拟环境用**（`#/postcard/admin?sim=1`）。`multipart`：`sender_name` / `grade_label` / `class_no` / `dest_region` / `dest_school` / `barcode` + 可选 `photo_front` / `photo_back`（走同一套照片安全管线）→ 用**与正式审核相同的 prompt 与解析**跑一次模型，返回 `{ok: true, verdict: {...}}`。
  - **不建登记单、不存照片、不写审计**；
  - AI 未配置 / 调用失败 → `{ok: false, reason: "ai_not_ready" | "ai_error"}`（HTTP 200），前端按「转人工复核」处理；
  - 限流 120/h（一张明信片一次调用）。

### 复核台

`GET admin/review/?state=manual_pending|ai_failed|`（空 = 全部待复核）：按**条目**聚合，返回 `{id, item_id, barcode, review_state, photo_ids, ai_verdict, registration}`，分页 20/页。

`POST admin/review/<item_pk>/`：`{"decision": "pass"|"fail", "note": "≤500"}`

- 仅接受 `manual_pending` / `ai_failed`，其余 400；
- `pass` → `manual_passed` 并**立即删除照片文件**；`fail` → `manual_failed`，照片留 24h TTL；
- 人工判定覆盖 AI 判定（原 `ai_verdict` 保留在 `manual.ai_verdict` 供追溯）；落审计；
- 通过 / 转人工后按发码规则即时亮码（服务端 `code_granted`）。

复核有新申请时向持 `events.review_postcard` 与 `events.manage_postcard` 的管理员发站内信；同一登记码的未读通知聚合为一条，跳转 `/#/reviews?kind=postcard`。

## 照片生命周期

| 时机 | 动作 |
|---|---|
| AI / 人工通过 | 立即删除照片文件（登记数据保留） |
| AI / 人工判定不通过 | 用户关标签页 `sendBeacon` 清理；24h TTL 兜底 |
| 活动结束 | 该活动全部照片文件清除（登记数据保留） |
| pending 卡死 >1h | 自动转人工复核 |

兜底命令（`scripts/install.sh` 会安装每小时 systemd timer）：

```bash
uv run python manage.py postcard_photo_gc
```

输出 JSON 统计：`ended_events_purged` / `ttl_purged` / `stale_pending_to_manual`。幂等，可重复执行。

## 权限与能力投影

| 权限代号 | 含义 |
|---|---|
| `events.manage_postcard` | 配置 / 条码 / 记录 / 导出 / 统计 / 建议 / 审计 / AI 配置与样例 / 海报导入 |
| `events.review_postcard` | 复核台 + 签收（管理权限隐含复核） |

`GET /auth/me/` 的能力投影：`can_manage_postcard` ← `events.manage_postcard`；`can_review_postcard` ← `events.review_postcard` **或** `events.manage_postcard` **或** 超管。能力键集是冻结契约，前端 `PermissionsPanel` 与 `CapabilityKeysContractTest` 同步。

## 前端入口

- 用户页 `/#/postcard`（独立页；主页「重大活动」与手机版首页「重大活动」入口，浏览器新标签页打开、App 壳内同窗口路由）。
- 管理端 `/#/postcard/admin`：六个分区——配置 / 条码 / AI / 记录 / 统计 / 建议与审计；复核并入 `/reviews` 的「明信片」桌。
- 模拟环境 `/#/postcard/admin?sim=1`（管理端右上「模拟活动」）：前端内存沙箱，管理端六分区 + 用户端登记 / 查询 / 历史 + 复核 + 签收全链路可演练；退出 / 刷新即清空。AI 判定走 `admin/ai/preview/` 真跑（不落库）。
- 签收页 `/#/postcard/receive`：扫 7 位条码定位并确认报寄。
- 三个路由均挂 `ProtectedRoute`；管理端权限真源在服务端，前端只做 403 提示。
- 审核台 `/#/reviews?kind=postcard`：复核并入统一审核台（桌面与手机版共用取数规则）。
