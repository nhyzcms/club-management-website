# 教程 API

「常用教程集锦」：已认证成员上传视频或文档，默认进入统一审核（待审 → 通过 / 驳回）；浏览侧只有收藏与去重播放量，**无评论、无弹幕、无点赞**。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0009](../adr/0009-portal-review-about-tutorials.md)（统一审核轴 · 教程原文件直播）、[ADR-0006](../adr/0006-verification-model.md)（认证通道）、[ADR-0005](../adr/0005-access-control-principle.md)（`has_perm` 判权）

挂载：`config/urls.py` 的 `tutorials/` + app 内 router 前缀 `tutorials`，路径均为 `/tutorials/tutorials/…`。列表响应为 DRF 分页信封（`PAGE_SIZE=20`）。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | /tutorials/tutorials/ | 公开 | — | 教程列表（已过审），分页 |
| POST | /tutorials/tutorials/ | 已认证 | — | 上传教程（multipart），自动开审核行 |
| GET | /tutorials/tutorials/mine/ | 已认证 | — | 我上传的教程（含待审 / 驳回），分页 |
| GET | /tutorials/tutorials/{id}/ | 公开 | — | 详情；已过审条目计去重播放量；作者可预览 |
| PUT / PATCH | /tutorials/tutorials/{id}/ | 登录 | 上传者或 `tutorials.manage_tutorials` | 编辑标题 / 描述等 |
| DELETE | /tutorials/tutorials/{id}/ | 登录 | 上传者或 `tutorials.manage_tutorials` | 删除 |
| POST | /tutorials/tutorials/{id}/favorite/ | 已认证 | — | 收藏 / 取消收藏（切换），返回最新详情 |

审核轴：`review_status` ∈ `pending` / `approved` / `rejected` / `removed`（无审核行为 `null`）；公开列表只出 `approved`。持 `reviews.force_publish` 或站点关闭 `content_review_enabled` 时上传即 `approved`。教程入库即生效（审核只门控公开展示，不改生命周期），视频不转码、原文件直播。**已过审教程再改标题 / 简介会退回 `pending` 重新入审**；`file_type` / `file_name` / `file_size` / `views` 为服务端派生字段，客户端不可写。

## 端点详情

### 教程列表
`GET /tutorials/tutorials/`

**认证**：公开；**权限**：—

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| page | 整数 | 否 | 页码（每页 20 条） |
| search | 字符串 | 否 | 模糊匹配 `title` / `description` |
| ordering | 字符串 | 否 | `created_at` / `views`，前缀 `-` 倒序；默认 `-created_at` |
| file_type | 字符串 | 否 | `video` 或 `document` |

**响应 `200 OK`**

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 9,
      "title": "Premiere 剪辑入门",
      "description": "30 分钟走完一次剪辑流程。",
      "file_type": "video",
      "file_name": "premiere-101.mp4",
      "file_size": 104857600,
      "cover_url": "https://8.153.145.175/media/tutorial_covers/7d2f0a91c4.jpg",
      "uploader": {"id": 4, "username": "student", "nickname": "小南", "avatar": "/media/avatars/2c3d.png"},
      "views": 57,
      "favorite_count": 6,
      "favorited": true,
      "review_status": "approved",
      "created_at": "2026-09-10T08:00:00Z"
    }
  ]
}
```

`favorited` 对匿名恒为 `false`；`file_url` 只在详情出现。

### 上传教程
`POST /tutorials/tutorials/`

**认证**：已认证（登录且账号已认证，任一认证通道通过）；**权限**：—

**请求体**（`multipart/form-data`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| title | 字符串 | 是 | 非空白；超 200 字符截断 |
| description | 字符串 | 否 | 超 2000 字符截断 |
| file | 文件 | 是 | 视频 mp4 / webm / ogv / mov，或文档 pdf / docx / doc（按 content-type 或扩展名判定）；≤ 500MB |
| cover | 图片文件 | 否 | 封面 |

服务端按文件类型落 `file_type` = `video` / `document`，并记录 `file_name`、`file_size`；同时创建审核行。

**响应 `201 Created`**

```json
{
  "id": 9,
  "title": "Premiere 剪辑入门",
  "description": "",
  "file_type": "video",
  "file_name": "premiere-101.mp4",
  "file_size": 104857600,
  "cover_url": null,
  "uploader": {"id": 4, "username": "student", "nickname": "小南", "avatar": null},
  "views": 0,
  "favorite_count": 0,
  "favorited": false,
  "review_status": "pending",
  "created_at": "2026-09-10T08:00:00Z",
  "file_url": "https://8.153.145.175/media/tutorials/9c31d0e8f7.mp4",
  "review_comment": "",
  "updated_at": "2026-09-10T08:00:00Z"
}
```

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 未带 `file`（`请上传视频或文档`）/ `title` 为空（`请填写标题`）/ 类型不支持（`仅支持视频（mp4/webm）或文档（pdf/docx）`）/ 超 500MB（`文件不能超过 500MB`） |
| 403 | 未登录或账号未认证（`请先完成账号认证后再使用此功能…`） |

### 我的上传
`GET /tutorials/tutorials/mine/`

**认证**：已认证；**权限**：—

返回当前用户上传的全部教程（含待审 / 驳回 / 下架），支持与列表相同的 `search` / `ordering` / `file_type` 参数。

**响应 `200 OK`**：与列表同形的分页信封。

### 教程详情
`GET /tutorials/tutorials/{id}/`

**认证**：公开；**权限**：—

可见性：公开只出 `approved`；上传者可预览自己的全部条目（作者预览）；不满足时返回 `404`。`review_comment` 仅上传者与持 `reviews.moderate` 者可见，其余人为空串。

计数：条目为 `approved` 时，每个新读者播放量 +1——登录按 `user:{pk}`、匿名按 `ip:{sha256(IP)}` 去重；未过审条目的预览不计播放量。

**响应 `200 OK`**

```json
{
  "id": 9,
  "title": "Premiere 剪辑入门",
  "description": "30 分钟走完一次剪辑流程。",
  "file_type": "video",
  "file_name": "premiere-101.mp4",
  "file_size": 104857600,
  "cover_url": "https://8.153.145.175/media/tutorial_covers/7d2f0a91c4.jpg",
  "uploader": {"id": 4, "username": "student", "nickname": "小南", "avatar": "/media/avatars/2c3d.png"},
  "views": 57,
  "favorite_count": 6,
  "favorited": true,
  "review_status": "approved",
  "created_at": "2026-09-10T08:00:00Z",
  "file_url": "https://8.153.145.175/media/tutorials/9c31d0e8f7.mp4",
  "review_comment": "",
  "updated_at": "2026-09-10T09:30:00Z"
}
```

**错误**

| 状态码 | 场景 |
|---|---|
| 404 | 条目不存在，或对当前读者不可见 |

### 编辑教程
`PUT /tutorials/tutorials/{id}/`、`PATCH /tutorials/tutorials/{id}/`

**认证**：登录；**权限**：上传者本人，或持 `tutorials.manage_tutorials`（对象级判定）

**请求体**：可写模型字段 `title`、`description`（以及 `file_type` / `file_name` / `file_size` / `views`）；换文件不在此序列化器（`file` / `cover` 不可写，需重新上传）。

**响应 `200 OK`**：详情结构（同上）。

**错误**

| 状态码 | 场景 |
|---|---|
| 403 | 非上传者且无 `tutorials.manage_tutorials` |
| 404 | 条目不存在 |

### 删除教程
`DELETE /tutorials/tutorials/{id}/`

**认证**：登录；**权限**：上传者本人，或 `tutorials.manage_tutorials`

**响应 `204 No Content`**。级联回收收藏与播放记录。

### 收藏 / 取消收藏
`POST /tutorials/tutorials/{id}/favorite/`

**认证**：已认证；**权限**：—

切换语义：未收藏则收藏、已收藏则取消（无请求体）。每人每教程至多一条收藏。

**响应 `200 OK`**：教程详情全部字段 + 最新的 `favorited` 与 `favorite_count`。

```json
{
  "id": 9,
  "title": "Premiere 剪辑入门",
  "description": "30 分钟走完一次剪辑流程。",
  "file_type": "video",
  "file_name": "premiere-101.mp4",
  "file_size": 104857600,
  "cover_url": "https://8.153.145.175/media/tutorial_covers/7d2f0a91c4.jpg",
  "uploader": {"id": 4, "username": "student", "nickname": "小南", "avatar": "/media/avatars/2c3d.png"},
  "views": 57,
  "favorite_count": 7,
  "favorited": true,
  "review_status": "approved",
  "created_at": "2026-09-10T08:00:00Z",
  "file_url": "https://8.153.145.175/media/tutorials/9c31d0e8f7.mp4",
  "review_comment": "",
  "updated_at": "2026-09-10T09:30:00Z"
}
```

**错误**

| 状态码 | 场景 |
|---|---|
| 403 | 未登录或账号未认证 |
| 404 | 条目不存在，或对当前读者不可见（如对他人未过审教程） |
