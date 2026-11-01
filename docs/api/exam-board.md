# 考试看板 API

考试看板：一场考试（`Exam`）→ 若干批次（`ExamBatch`）→ 若干科目场次（`ExamSubject`）；职员发布**题目误刊**（`ExamErrata`）后经公开 WebSocket 广播到所有打开的看板。HTTP 提供课表、授时与误刊，读写均匿名可读、持权可写。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0018](../adr/0018-exam-board-batch-and-public-ws.md)（批次课表 + 公开 WebSocket）、[ADR-0015](../adr/0015-channels-without-redis.md)（单 ASGI worker · 内存通道层）、[ADR-0005](../adr/0005-access-control-principle.md)（`has_perm` 判权）

挂载：`config/urls.py` 的 `exam_board/`；WebSocket 在 `config/asgi.py` 注册 `/ws/exam-board/`。科目日期与时刻按 **Asia/Shanghai 墙钟**解读（全局 `TIME_ZONE` 仍为 UTC）；考试列表为 DRF 分页信封（`PAGE_SIZE=20`）。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | /exam_board/exams/ | 公开 | — | 考试列表（按 id 倒序），分页 |
| POST | /exam_board/exams/ | 登录 | `exam_board.manage_exams` | 新建考试（含批次 / 科目），广播 `exam` |
| GET | /exam_board/exams/latest/ | 公开 | — | 最新一场考试的完整课表 |
| GET | /exam_board/exams/clock/ | 公开 | — | 授时：上海墙钟 |
| GET | /exam_board/exams/{id}/ | 公开 | — | 考试详情（批次 + 科目场次） |
| PUT / PATCH | /exam_board/exams/{id}/ | 登录 | `exam_board.manage_exams` | 编辑考试，广播 `exam` |
| DELETE | /exam_board/exams/{id}/ | 登录 | `exam_board.manage_exams` | 删除考试，广播 `exam` |
| GET | /exam_board/errata/current/ | 公开 | — | 当前未撤回的题目误刊，顺带撤回已过期条目 |
| POST | /exam_board/errata/ | 登录 | `exam_board.manage_exams` | 发布题目误刊，广播 `errata` |
| POST | /exam_board/errata/dismiss/ | 登录 | `exam_board.manage_exams` | 撤回误刊，广播 `errata_cleared` |
| WS | /ws/exam-board/ | 公开 | — | 看板推送（只收不发） |

误刊到期时刻跟科目场次走：发布时若该考试（或指定批次）有进行中的场次，取该场结束时刻；没有进行中场次则立即到期。本场结束按 id 升序依次失效。

## 端点详情

### 考试列表
`GET /exam_board/exams/`

**认证**：公开；**权限**：—

**查询参数**：`page`（页码，每页 20 条）。

**响应 `200 OK`**

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {"id": 12, "title": "2026 学年第一学期期末", "batch_count": 2,
     "created_at": "2026-09-15T02:00:00Z", "updated_at": "2026-09-16T07:30:00Z"},
    {"id": 11, "title": "开学考", "batch_count": 1,
     "created_at": "2026-08-20T02:00:00Z", "updated_at": "2026-08-20T02:00:00Z"}
  ]
}
```

### 新建考试
`POST /exam_board/exams/`

**认证**：登录；**权限**：`exam_board.manage_exams`

**请求体**（JSON / multipart）

```json
{
  "title": "2026 学年第一学期期末",
  "batches": [
    {
      "name": "高一",
      "sort_order": 0,
      "subjects": [
        {"name": "语文", "exam_date": "2026-01-10", "start_time": "09:00", "end_time": "11:30"},
        {"name": "数学", "exam_date": "2026-01-10", "start_time": "14:00", "end_time": "16:00"}
      ]
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| title | 字符串 | 是 | 非空白，≤ 50 |
| batches | 数组 | 是 | 至少一个；批次名同一考试内不得重复 |
| batches[].name | 字符串 | 是 | 非空白 |
| batches[].sort_order | 整数 | 否 | 缺省按数组顺序 |
| batches[].subjects | 数组 | 是 | 可为空数组 |
| subjects[].name | 字符串 | 是 | 非空白 |
| subjects[].exam_date | 日期 `YYYY-MM-DD` | 是 | |
| subjects[].start_time / end_time | 时刻 `HH:MM[:SS]` | 是 | `end_time` 必须晚于 `start_time` |
| subjects[].sort_order | 整数 | 否 | 缺省按数组顺序 |

校验（400）：同一批次同一天的科目时间不得重叠；首尾相接（结束 = 下一场开始）允许——间隙即为休息，不建模。

**响应 `201 Created`**（详情结构，见下节），并广播 `exam`。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 标题为空 / 无批次 / 批次名重复 / 科目名为空 / 结束不晚于开始 / 同批次同日重叠 |
| 403 | 匿名或未持 `exam_board.manage_exams` |

### 最新考试课表
`GET /exam_board/exams/latest/`

**认证**：公开；**权限**：—

取 id 最大的一场考试，返回完整批次与科目（同详情结构）。无论有无数据状态码都是 `200`。

**响应 `200 OK`**

```json
{
  "status": "success",
  "data": {
    "id": 12,
    "title": "2026 学年第一学期期末",
    "batches": [
      {
        "id": 21,
        "name": "高一",
        "sort_order": 0,
        "subjects": [
          {"id": 55, "name": "语文", "exam_date": "2026-01-10",
           "start_time": "09:00:00", "end_time": "11:30:00", "sort_order": 0}
        ]
      }
    ],
    "created_at": "2026-09-15T02:00:00Z",
    "updated_at": "2026-09-16T07:30:00Z"
  }
}
```

无数据时：`{"status": "success", "data": null, "message": "数据库中暂无考试数据"}`。

### 授时
`GET /exam_board/exams/clock/`

**认证**：公开；**权限**：—

**响应 `200 OK`**

```json
{
  "timestamp": 1789458600000,
  "timezone": "Asia/Shanghai",
  "iso": "2026-09-19T09:30:00+08:00"
}
```

`timestamp` 为 Unix 毫秒。看板不再外调第三方授时；课表与误刊的「现在」均以此墙钟为准。

### 考试详情
`GET /exam_board/exams/{id}/`

**认证**：公开；**权限**：—

**响应 `200 OK`**：`{"id", "title", "batches": [ExamBatch…], "created_at", "updated_at"}`；批次含 `id`、`name`、`sort_order`、`subjects`（科目含 `id`、`name`、`exam_date`、`start_time`、`end_time`、`sort_order`）。

**错误**

| 状态码 | 场景 |
|---|---|
| 404 | 考试不存在 |

### 编辑考试
`PUT /exam_board/exams/{id}/`、`PATCH /exam_board/exams/{id}/`

**认证**：登录；**权限**：`exam_board.manage_exams`

**请求体**：同新建。传 `batches` 时**整体替换**（旧批次与科目全部删除后按新数组重建），不传则只改标题。校验规则同新建。

**响应 `200 OK`**：详情结构，并广播 `exam`。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 同新建校验 |
| 403 | 匿名或未持 `exam_board.manage_exams` |
| 404 | 考试不存在 |

### 删除考试
`DELETE /exam_board/exams/{id}/`

**认证**：登录；**权限**：`exam_board.manage_exams`

**响应 `204 No Content`**。级联删除批次、科目场次与该考试的误刊；广播 `exam`。

### 当前题目误刊
`GET /exam_board/errata/current/`

**认证**：公开；**权限**：—

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| exam | 整数 | **是** | 仅取该考试；缺省或非整数返回 400（防止跨场次误刊混入） |

副作用：先撤回 `expires_at ≤ 现在` 的条目；带 `exam` 参数且该场当前没有进行中的科目场次时，剩余未撤回误刊一并撤回。撤回按 id 升序并广播一次 `errata_cleared`。

**响应 `200 OK`**

```json
{
  "status": "success",
  "data": [
    {"id": 31, "exam": 12, "text": "第 3 题第 2 问题干漏印「不」字，以更正后为准。",
     "image_url": "https://8.153.145.175/media/exam_errata/4f8a1c92d0.png",
     "created_at": "2026-01-10T01:05:00Z", "expires_at": "2026-01-10T03:30:00Z"},
    {"id": 32, "exam": 12, "text": "第 18 题选 C。",
     "image_url": null,
     "created_at": "2026-01-10T01:20:00Z", "expires_at": "2026-01-10T03:30:00Z"}
  ]
}
```

### 发布题目误刊
`POST /exam_board/errata/`

**认证**：登录；**权限**：`exam_board.manage_exams`

**请求体**（multipart 或 JSON）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| exam | 整数 | 是 | 该误刊所属考试 id |
| text | 字符串 | 否 | 说明，≤ 500；与 `image` 至少有一项非空 |
| image | 文件 | 否 | jpeg / png / gif / webp，≤ 5MB |
| batch | 整数 | 否 | 批次 id：把到期时刻限定在该批次当天进行中的场次；不属于 `exam` 时忽略 |

多条误刊可同时存在，新条不覆盖旧条。发布成功后向 `/ws/exam-board/` 广播 `errata`。

**响应 `201 Created`**

```json
{
  "id": 31,
  "exam": 12,
  "text": "第 3 题第 2 问题干漏印「不」字，以更正后为准。",
  "image_url": "https://8.153.145.175/media/exam_errata/4f8a1c92d0.png",
  "created_at": "2026-01-10T01:05:00Z",
  "expires_at": "2026-01-10T03:30:00Z"
}
```

`expires_at` 为发布时算出的本场结束时刻（上海墙钟取当前日期）；当前无进行中场次时等于发布时间（立即到期）。`image` 只写不出。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 缺 `exam` / `text` 与 `image` 全空 / 图片类型或大小不合规 |
| 403 | 匿名或未持 `exam_board.manage_exams` |

### 撤回题目误刊
`POST /exam_board/errata/dismiss/`

**认证**：登录；**权限**：`exam_board.manage_exams`

**请求体 / 查询参数**：`exam`（整数，必填）——JSON body 或 `?exam=` 均可；缺省返回 400，不能一次撤回全部场次。撤回成功才广播 `errata_cleared`。

**响应 `200 OK`**

```json
{"status": "success", "dismissed": 2, "ids": [31, 32]}
```

**错误**

| 状态码 | 场景 |
|---|---|
| 403 | 匿名或未持 `exam_board.manage_exams` |

## WebSocket：看板推送

`ws(s)://<host>/ws/exam-board/`

**认证**：无——匿名（教室大屏）可连；仍做 Origin 校验（`AllowedHostsOriginValidator`），须与站点同源。**语义**：只收不发，客户端发送的消息被忽略。进组名 `exam_board`。

**服务端消息信封**

```json
{"event": "errata", "payload": {"id": 31, "exam": 12, "text": "第 3 题第 2 问题干漏印「不」字，以更正后为准。", "image_url": "https://8.153.145.175/media/exam_errata/4f8a1c92d0.png", "created_at": "2026-01-10T01:05:00Z", "expires_at": "2026-01-10T03:30:00Z"}}
```

| event | payload | 触发时机 |
|---|---|---|
| `exam` | `{"exam_id": 12}` | 考试新建 / 编辑 / 删除 |
| `errata` | 与 `POST /exam_board/errata/` 的 `201` 响应同形的误刊对象 | 发布新误刊 |
| `errata_cleared` | `{"ids": [31, 32], "exam_id": 12}`（`exam_id` 可为 `null`） | 撤回误刊 / `current` 顺带撤回过期条目 |

HTTP 是事实源：socket 只提示刷新——收到 `exam` 重新拉课表，收到 `errata` / `errata_cleared` 刷新弹窗并回读 `GET /exam_board/errata/current/`；断线重连后同样重新拉取。

部署约束（[ADR-0015](../adr/0015-channels-without-redis.md)）：v1 单 ASGI worker + 进程内 `InMemoryChannelLayer`，广播只到达同一进程内的连接。
