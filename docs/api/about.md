# 关于 API

「关于我们」页：固定五块富文本区块（关于社团 / 关于一中 / 关于网站 / 联系我们 / 校园一览）+ 社团概览静态行；公开读，持 `about.manage_aboutpage` 者编辑，**不按块拆权限**。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0009](../adr/0009-portal-review-about-tutorials.md)（关于多区块 · 文档保真导入）、[ADR-0005](../adr/0005-access-control-principle.md)（`has_perm` 判权）

挂载：`config/urls.py` 的 `about/`。五块按 `order`、`id` 升序输出，`key` 固定，不提供新建 / 删除接口。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | /about/ | 公开 | — | 门户聚合：全部区块 + 社团概览 |
| GET | /about/overview/ | 公开 | — | 社团概览静态行（成立 / 指导 / 简介） |
| PUT / PATCH | /about/overview/ | 登录 | `about.manage_aboutpage` | 编辑静态行 |
| GET | /about/blocks/{key}/ | 公开 | — | 读取单个区块 |
| PATCH | /about/blocks/{key}/ | 登录 | `about.manage_aboutpage` | 编辑区块：标题 / 正文 / 全景外链 / 文档附件 |

> **限流**（审计 #280）：`/about/`、`/about/overview/`、`/about/blocks/{key}/` 的**安全方法**共用一个按 IP 的读桶，默认 `300/min`，超出回 `429`（DRF 标准 `{"detail": …}`，文案已本地化为中文）。写方法（`PUT`/`PATCH`）不计入这个桶——管理员的保存不该占访客的读额度。速率取 300 而非更严的值，是因为学校网络整栋楼共用 NAT 出口，一个班同时刷名册就会撞上 120/min。

五个固定键：`club`（关于社团）、`school`（关于一中）、`site`（关于网站）、`contact`（联系我们）、`campus-overview`（校园一览）。「校园一览」正文下方固定一个「校园全景图」按钮，外链到 `panorama_url`。

## 端点详情

### 关于页聚合
`GET /about/`

**认证**：公开；**权限**：—

**响应 `200 OK`**

```json
{
  "blocks": [
    {
      "key": "club",
      "title": "关于我们",
      "content": "<p>南汇一中传媒社成立于 2026 年 3 月。</p>",
      "order": 0,
      "panorama_url": "",
      "document_url": null,
      "document_name": "",
      "updated_at": "2026-09-11T03:00:00Z"
    },
    {
      "key": "campus-overview",
      "title": "校园一览",
      "content": "<p>校园图文综述。</p>",
      "order": 4,
      "panorama_url": "https://panorama.example/nhyz",
      "document_url": null,
      "document_name": "",
      "updated_at": "2026-09-11T03:00:00Z"
    }
  ],
  "overview": {
    "founded": "2026.03",
    "advisor": "信息组",
    "intro": "用镜头记录青春",
    "updated_at": "2026-09-11T03:00:00Z"
  },
  "updated_at": "2026-09-11T03:00:00Z"
}
```

实际返回五块（示例截取首尾两块）。`updated_at` 为单例（关于页）自身的更新时间；单例上的历史 `title` / `content` 字段不再经 API 输出，编辑以区块为准。

**错误**

| 状态码 | 场景 |
|---|---|
| 405 | 对 `/about/` 使用 PUT / PATCH / DELETE（视图只接受 GET，编辑走下面两个端点） |

### 读取社团概览
`GET /about/overview/`

**认证**：公开；**权限**：—

**响应 `200 OK`**

```json
{
  "founded": "2026.03",
  "advisor": "信息组",
  "intro": "用镜头记录青春",
  "updated_at": "2026-09-11T03:00:00Z"
}
```

成员数 / 作品数不在此端点，走 [新闻 API](news.md) 的 `GET /news/news/overview/`（实时统计）。

### 编辑社团概览
`PUT /about/overview/`、`PATCH /about/overview/`

**认证**：登录；**权限**：`about.manage_aboutpage`

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| founded | 字符串 | 否 | 提供时去空白后不得为空、≤ 40；缺省保留原值 |
| advisor | 字符串 | 否 | 提供时去空白后不得为空、≤ 80；缺省保留原值 |
| intro | 字符串 | 否 | 简介，超 200 字符截断 |

**响应 `200 OK`**：同读取结构。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 提供了 `founded` / `advisor` 但为空或超长 |
| 403 | 匿名或未持 `about.manage_aboutpage` |

### 读取单个区块
`GET /about/blocks/{key}/`

**认证**：公开；**权限**：—

**路径参数**：`key` 为五个固定键之一（Slug）。

**响应 `200 OK`**

```json
{
  "key": "campus-overview",
  "title": "校园一览",
  "content": "<p>校园图文综述。</p>",
  "order": 4,
  "panorama_url": "https://panorama.example/nhyz",
  "document_url": "https://8.153.145.175/media/about_documents/campus-overview.pdf",
  "document_name": "campus-overview.pdf",
  "updated_at": "2026-09-11T03:00:00Z"
}
```

`document_url` 无附件时为 `null`，`document_name` 为 `""`。

**错误**

| 状态码 | 场景 |
|---|---|
| 404 | `key` 不存在 |

### 编辑区块
`PATCH /about/blocks/{key}/`

**认证**：登录；**权限**：`about.manage_aboutpage`

**请求体**（JSON 或 multipart；上传文档时用 multipart）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| title | 字符串 | 否 | 区块标题 |
| content | 字符串 | 否 | 富文本 HTML，服务端经 `sanitize_html` 清洗 |
| panorama_url | 字符串 | 否 | 须以 `http://` 或 `https://` 开头（空白视为清除） |
| document | 文件 | 否 | PDF 或 .docx，≤ 20MB；上传即替换旧附件 |
| clear_document | 字符串 | 否 | `1` / `true` / `yes`（不分大小写）时删除当前附件 |

**响应 `200 OK`**：更新后的区块结构（同上）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | `panorama_url` 非 http(s)；`document` 非 PDF / .docx（`仅支持 PDF 或 .docx`）或超 20MB（`文档不能超过 20MB`） |
| 403 | 匿名或未持 `about.manage_aboutpage` |
| 404 | `key` 不存在 |
| 405 | 对区块使用 PUT（视图只开放 GET 与 PATCH） |
