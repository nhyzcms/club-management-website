# 附件与上传 API

统一附件子系统：一张 `Attachment` 表可挂在**恰好一个**父级（任务 / 意见反馈 / 新闻 / 作品 / 展品）上；小文件走同步 `POST /attachments/`，大图 / 视频走 tus 可续传 `/uploads/files/`。附件无独立列表端点——列表随父级详情返回；删除统一走 `DELETE /attachments/{id}/`。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0001](../adr/0001-unified-attachment-nullable-fks.md)、[ADR-0002](../adr/0002-unified-attachment-endpoint-and-permission.md)、[ADR-0004](../adr/0004-feedback-media-tus-resumable-upload.md)、[ADR-0012](../adr/0012-attachment-create-seam.md)

## 模块约定

- **挂载前缀**：`config/urls.py` 把 `attachments/urls.py` 挂在 `/attachments/`（`SimpleRouter`，资源前缀为空 → `/attachments/` 与 `/attachments/{id}/`）；`attachments/tus_urls.py` 挂在 `/uploads/`（`TusAPIRouter`，注册 `files` → `/uploads/files/` 与 `/uploads/files/{guid}/`）。
- **父级注册表**（`attachments/create.py` 的 `PARENTS`）：`task` / `feedback` / `news` 是**增量父级**（`endpoint=True`，HTTP 与 tus 可用）；`submission`（作品）/ `exhibit`（展品）**不是** HTTP 父级——投稿 / 布展是原子批量，由活动侧适配器调用同一创建接缝（[ADR-0012](../adr/0012-attachment-create-seam.md)）。
- **权限单一抽象规则**（[ADR-0002](../adr/0002-unified-attachment-endpoint-and-permission.md)）：操作者须为该父级的**创建者**、或**活跃参与者**、或持该父级**管理权限**者。父级差异：

  | 父级 | 创建者 | 活跃参与者 | 管理权限 |
  |---|---|---|---|
  | 任务 | `creator` | 进行中（`in_progress`）时的负责人 / 协作者（`tasks.lifecycle.is_active_participant`） | `tasks.manage_tasks` |
  | 意见反馈 | `creator`（署名反馈） | 无 | `reviews.read_feedback` |
  | 新闻 | `author` | 无 | `news.manage_news` |
  | 作品 | —（注册表无创建者字段） | 无 | 活动发起人，或 `activities.manage_activity`，或 `activities.review_collection` |
  | 展品 | —（同上） | 无 | 活动发起人（策展人），或 `activities.manage_activity` |

- **反馈 carve-out**（[ADR-0004](../adr/0004-feedback-media-tus-resumable-upload.md)）：**上传**仅**署名创建者**且反馈仍 `pending`（持 `read_feedback` 的社长被排除）；**删除**在 `pending` 时沿用通用规则——故社长对反馈附件「能删不能传」。**审结（`closed`）后证据附件仅 `reviews.read_feedback` 持有者可删**（上传者本人也不行，`403 反馈已了结，证据附件仅处理人可删除`），防止审计链断裂；审结同时锁死上传。
- **回收**：父级删除 → 外键 `CASCADE` 逐行删附件 → `post_delete` 信号同步删磁盘文件（无需定时任务）；删除附件行同路径。举报案不挂附件。
- **上传分档**（站点策略，见[公共 API](common.md)）：≤`sync_upload_max_bytes`（默认 50MB）任意类型走同步；>50MB 必须图片 / 视频且 ≤`tus_media_max_bytes`（默认 500MB）走 tus。反馈附件配额：每条 ≤9 个、总量 ≤2GB（两条通路共用校验）。
- **认证口径**：两套端点均为 `IsAuthenticated`（登录；DRF 会话认证下未登录返回 403 `{"detail": …}`，与全局约定一致）。
- **禁用扩展名**：命中 `common/uploads.RESTRICTED_EXTENSIONS` 一律拒——HTML / SVG / XML / JS / CSS、服务端脚本（php / asp / jsp）、本地可执行（exe / bat / sh / py / dll…）。**同步与 tus 两条通路共用**，且 `upload_to` 落盘前还有兜底（未知扩展名退回 `.bin`）。图片按 Pillow 真实解码判定格式、PDF 按 `%PDF-` 魔数；客户端 `content_type` 不作为判据。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| POST | `/attachments/` | 登录 | 父级创建者 / 活跃参与者 / 管理权限（反馈另受 carve-out） | 同步上传（multipart，≤50MB） |
| DELETE | `/attachments/{id}/` | 登录 | 上传者本人，或父级管理规则（反馈了结后仅处理人可删） | 删除附件（行 + 磁盘文件） |
| POST | `/uploads/files/` | 登录 | 同上传（含反馈 carve-out） | 创建 tus 上传会话（校验父级 / 权限 / 尺寸 / 配额） |
| HEAD | `/uploads/files/{guid}/` | 登录 | — | 查询上传偏移（续传用） |
| PATCH | `/uploads/files/{guid}/` | 登录 | — | 续传分片（`application/offset+octet-stream`） |
| DELETE | `/uploads/files/{guid}/` | 登录 | — | 终止上传会话（回收临时文件） |

`/attachments/` 为 `SimpleRouter` 注册、仅暴露 `create` / `destroy` 两个 action——`GET /attachments/`、`PUT`、`PATCH` 均为 405（`{"detail": "Method \"…\" not allowed."}`），列表随父级详情返回。tus 详情路由注册了 `PUT`（映射到 `update`），但该 action 一律抛 405；实际只用 `HEAD` / `PATCH` / `DELETE`。

## 端点详情

### 同步上传附件

`POST /attachments/`

**认证**：登录；**权限**：`can_upload_to_parent`（见模块约定的抽象规则与反馈 carve-out）。请求体 `multipart/form-data`。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| file | file | 是 | 待上传文件；≤`sync_upload_max_bytes`；类型 / 扩展名过安全闸门（见上） |
| task_id | int | 三选一 | 任务父级 id（`endpoint=True`） |
| feedback_id | int | 三选一 | 意见反馈父级 id |
| news_id | int | 三选一 | 新闻父级 id |

**必须且只能指定一个父级**——`task_id` / `feedback_id` / `news_id` 中恰填一个（`submission_id` / `exhibit_id` 会被拒）。`file_type` 由 content-type 推断：`image/*`→`image`、`video/*`→`video`、PDF / Office / 纯文本→`document`、zip / rar / 7z / gzip→`archive`、其余→`other`。

**响应 `201 Created`**

```json
{
  "id": 41,
  "file_url": "http://localhost:8000/media/attachments/9f1c2ab3d4e5f6a7b8c9d0e1f2a3b4c5.png",
  "file_type": "image",
  "file_name": "evidence.png",
  "file_size": 204800,
  "uploaded_by": {"id": 7, "username": "zhangsan", "nickname": "张三", "avatar": null},
  "uploaded_at": "2026-09-19T03:20:00+00:00"
}
```

`file_url` 为绝对 URL（`request.build_absolute_uri`；无 request 上下文时退化为相对路径，无文件时为 `null`）。`uploaded_by` 复用全站 `SimpleUserSerializer`（`id` / `username` / `nickname` / `avatar`；仅查看自己时额外带 `email`）。`file_size` 为字节数（`BigInteger`）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 未选文件 `{"detail": "请选择文件"}`；超同步上限或禁用扩展名；父级个数不为 1 `{"detail": "必须且只能指定一个父级（task_id / feedback_id / news_id）"}`；反馈配额超限 |
| 403 | 无该父级上传权限 `{"detail": "无权操作此父级的附件"}` |
| 404 | 父级不存在 `{"detail": "指定的父级不存在"}` |

### 删除附件

`DELETE /attachments/{id}/`

**认证**：登录；**权限**：`can_manage_parent_attachments`（父级通用规则）**或**该附件的上传者本人（上传者始终可删自己上传的）。

**响应 `204 No Content`**：无响应体。删除附件行，`post_delete` 信号同步回收磁盘文件（FS 异常只记日志，不向用户抛错）。

**错误**：403 `{"detail": "无权删除此附件"}`；404 附件不存在。

### tus 上传：创建会话

`POST /uploads/files/`

**认证**：登录；**权限**：`can_upload_to_parent`（同同步上传，含反馈 carve-out）。遵循 [tus 1.0.0](https://tus.io/protocols/resumable-upload.html) 协议；请求头见下。

**请求头**

| 头 | 必填 | 说明 |
|---|---|---|
| Tus-Resumable | 是 | 固定 `1.0.0`；缺失返回 400 |
| Upload-Length | 是 | 文件总字节数（或 `Upload-Defer-Length: 1` 声明稍后补，二者至少其一） |
| Upload-Metadata | 是 | `key base64(value)` 逗号分隔；须带 `parent_type` 与 `parent_id`，建议带 `filename` 与 `filetype` |
| Content-Type | — | `application/octet-stream`（客户端惯例） |

`Upload-Metadata` 键值：`parent_type` ∈ `task` / `feedback` / `news`（作品 / 展品不走 tus）、`parent_id`（父级数字 id）、`filename`（落成附件时的 `file_name`）、`filetype`（落成附件时的 content-type，用于分类）。

**请求体**：无（创建时不传字节）。

**响应 `201 Created`**（无响应体，除库设置外；关键为响应头）

| 响应头 | 说明 |
|---|---|
| Location | `/uploads/files/{guid}/`——后续 HEAD / PATCH / DELETE 的目标 |
| Tus-Resumable | `1.0.0` |
| Upload-Expires | 会话过期时间（默认创建后 1 天；过期会话由下次创建时惰性回收） |

**创建期校验**（全部在接收任何字节之前）：父级缺失 / 非法 → 400；无权限 → 403；`Upload-Length` 超 `tus_media_max_bytes` → **413**；超同步上限但 `filetype` 非图片 / 视频 → 400；反馈配额超限 → 400。

> **数字头格式闸门**（审计 #273）：`Upload-Length` / `Upload-Offset` 必须是**非负十进制整数**（≤20 位）。畸形值（`abc`、`1e9`、负数、5000 位数字串、任何非数字）在进入 DRF 之前就被 `attachments.middleware.TusHeaderValidationMiddleware` 拦成 **400 `{"detail": "Upload-Length 必须是非负整数。"}`**，响应带 `Tus-Resumable: 1.0.0`。
>
> 这层是必要的：`drf-tus` 2.0.3 的 `TusMiddleware` 直接 `int()` 头值且无异常处理，**且不判路径**——不带这层时，任何 URL 上带 `Upload-Length: abc` 都会 500（不只是 `/uploads/`）。闸门比 `TusMiddleware` 更早执行，因此匿名也能被正确拒绝（400 而非 500）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 缺 `Tus-Resumable`；缺 / 非法父级 `{"detail": "缺少或无效的父级（Upload-Metadata 需带 parent_type 与 parent_id）"}`；非图 / 视频超 50MB；反馈配额 |
| 403 | 无该父级上传权限 `{"detail": "无权为此父级上传附件"}` |
| 413 | `Upload-Length` 超过 tus 上限 |

### tus 上传：查询偏移

`HEAD /uploads/files/{guid}/`

**认证**：登录；**权限**：—。续传前查询已接收偏移。

**响应 `200 OK`**（无体）：`Upload-Offset`（已接收字节数）、`Upload-Length`、`Upload-Metadata`、`Upload-Expires`、`Cache-Control: no-store`。**错误**：400 缺 `Tus-Resumable`；404 会话不存在。

### tus 上传：续传分片

`PATCH /uploads/files/{guid}/`

**认证**：登录；**权限**：—。`Content-Type: application/offset+octet-stream`（否则 400）；`Upload-Offset` 必须等于服务端当前偏移（不等返回 409 Conflict）。请求体为该偏移处的字节块（可分片多次调用）。

**响应 `204 No Content`**：响应头带新 `Upload-Offset`。最后一次分片（`upload_offset == upload_length`）时触发 `finished` 信号：**复核权限**（父级状态可能已变——反馈审结、任务关闭——复核失败即丢弃上传、不建附件），通过则把文件搬成统一 `Attachment` 并清理 tus 落地副本；tus 会话行由下次创建时的惰性回收清除。

**错误**：400 缺 `Tus-Resumable` / Content-Type 不符 / 空分片 / 校验和算法不支持；409 偏移不匹配；460 校验和不符（`Upload-Checksum`）。

### tus 上传：终止

`DELETE /uploads/files/{guid}/`

**认证**：登录；**权限**：—。删除会话并回收临时分片与落地副本。**响应 `204 No Content`**；错误：409 会话处于保存中状态时不可终止。

## 附件的父级内联形态

附件没有独立列表端点；各父级详情序列化器以 `attachments` 数组内联输出同一 `AttachmentSerializer` 字段：

| 父级 | 内联位置 | 字段 |
|---|---|---|
| 任务 | 任务详情 `attachments`（`tasks.serializers`） | 完整 `AttachmentSerializer`（含 `uploaded_by` / `uploaded_at`） |
| 意见反馈 | 反馈详情 `attachments`（`reviews.serializers`） | 同上 |
| 新闻 | 新闻详情 `attachments`（`news.serializers.NewsAttachmentSerializer`） | 精简：`id` / `file_url` / `file_type` / `file_name` / `file_size`（详情匿名可读，故不含 `uploaded_by`） |
| 作品 / 展品 | 活动详情内对应对象的 `files` 字段（`activities.serializers` 的 `SubmissionSerializer` / `ExhibitSerializer`） | 完整 `AttachmentSerializer` |

客户端上传大文件（`attachmentApi.uploadLarge`）完成后接口返回 `void`——须**重新拉取父级详情**才能拿到新附件；同步上传则直接返回新建的 `Attachment`（响应体字段同上传端点）。

## 相关实现位置

| 关注点 | 位置 |
|---|---|
| 统一模型与约束 | `attachments/models.py`（`Attachment`、`TusUpload`；CheckConstraint「恰好一个父级」） |
| 创建接缝 | `attachments/create.py`（`PARENTS` / `create_attachment` / `copy_attachment` / `parent_of`） |
| 权限谓词 | `attachments/permissions.py`（`can_upload_to_parent` / `can_manage_parent_attachments`） |
| 校验与配额 | `attachments/validation.py`（`upload_error` / `classify_file_type` / `feedback_quota_error`） |
| tus 集成 | `attachments/tus.py`（`TusUploadViewSet` / `finished` 接收器 / `sweep_stale_tus_uploads`） |
| 磁盘回收 | `attachments/signals.py`（`post_delete`） |
