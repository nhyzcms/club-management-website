# API 总览

本目录是南汇一中传媒社社团管理系统的 HTTP / WebSocket 接口参考，按模块分册。所有接口由 Django + Django REST Framework 提供，Web 端、移动版与嵌入页共用同一套。

> 推荐阅读顺序：本篇（全局约定）→ [访问控制指南](../guides/access-control.md) 与 [身份验证指南](../guides/verification.md)（权限体系）→ 各模块分册。

## 基本约定

### 认证

- 接口采用**浏览器会话认证**（DRF `SessionAuthentication`）：登录成功后以 `sessionid` cookie 维持会话，跨源调用需携带凭据（`credentials: include`）。
- 全局默认权限为「登录」；公开接口在各视图上显式放开（如新闻、教程、关于页的读取）。
- 部分能力额外要求「身份已验证」或持有具体权限（`has_perm`），各模块文档逐端点注明。

### CSRF

- 一切**非安全方法**（POST / PUT / PATCH / DELETE）必须携带 `X-CSRFToken` 请求头。
- 获取方式：`GET /auth/csrf/` 会下发 `csrftoken` cookie，前端从 cookie 读值回填请求头。

### 设备标识

- 匿名场景需携带 `X-Device-Id` 请求头（浏览器侧生成、存 localStorage 的 UUID），用于设备级约束（如公开问卷「一设备一份」）。

### 分页

- 列表接口统一为**页码分页**（见 [ADR-0008](../adr/0008-list-pagination.md)）：默认每页 20 条，响应信封固定：

```json
{
  "count": 128,
  "next": "https://…/news/?page=3",
  "previous": "https://…/news/?page=1",
  "results": [ "…" ]
}
```

### 过滤与排序

- 支持 `?search=`（搜索）与 `?ordering=`（排序）的列表在各模块文档中注明；部分接口另有字段过滤参数。

### 错误格式

- DRF 视图错误：`{"detail": "…"}`；函数式视图错误：`{"error": "…"}`。
- 常见状态码：

| 状态码 | 含义 |
|---|---|
| 400 | 参数错误（具体见各模块文档） |
| 401 | 未登录或会话失效 |
| 403 | 已登录但权限不足（或 CSRF 校验失败） |
| 404 | 资源不存在或不可见 |
| 409 | 状态冲突；登录保护期（`login_protection`，携带 `retry_after`，单位秒） |
| 429 | 登录限流（`login_throttled`，携带 `retry_after`，单位秒） |
| 503 | 维护模式（全站，期间不触达业务） |

- **会话契约**：登录态相关的特殊结果通过响应体 `reason` 字段区分（前端按类型化错误分支处理，不匹配文案）：

| reason | 场景 | 载荷 |
|---|---|---|
| `session_superseded` | 账号在其它设备登录，本会话被接管下线 | `takeover: { device_name, device_type, ip, time }` |
| `login_protection` | 目标账号 10 分钟内在其它设备登录过，新登录处于保护期 | `retry_after` |
| `login_throttled` | 登录尝试过于频繁 | `retry_after` |
| `account_disabled` | 账号已停用 | — |
| `account_expired_unverified` | 超期未认证被系统停用（登录被拒，携专属文案） | — |
| `email_not_verified` | 邮箱未验证，登录被拒 | `email` |

### 实时通道（WebSocket）

| 路径 | 认证 | 用途 | 文档 |
|---|---|---|---|
| `/ws/messaging/` | 登录 | 评论 / 私信 / 通知的实时推送 | [messaging](messaging.md) |
| `/ws/exam-board/` | 公开 | 题目误刊广播 | [exam-board](exam-board.md) |

握手与 HTTP 共用会话 cookie，并校验 `Origin`（与 `ALLOWED_HOSTS` 一致）。

### 文件上传

- 普通上传：`multipart/form-data`，走附件模块接口（见 [attachments](attachments.md)）。
- 大文件**断点续传**：TUS 协议，挂载在 `/uploads/`；大小上限由站点策略控制（库级兜底 500 MB）。
- **全景图导入**是独立的同步上传通路（不受附件 / tus 体系管辖，服务端要做切片）：见 [panorama](panorama.md)。上限复用站点策略的「同步上传单文件上限」。

## 模块索引

| 模块 | 文档 | 说明 |
|---|---|---|
| 账号与认证 | [accounts](accounts.md) | 注册 / 登录 / 验证 / 资料 / 能力投影 |
| 新闻 | [news](news.md) | 社团新闻，发布审核门控 |
| 活动 | [activities](activities.md) | 众议 / 征集 / 展示 / 调研四类活动与问卷 |
| 任务 | [tasks](tasks.md) | 任务与标签，状态机流转 |
| 教程 | [tutorials](tutorials.md) | 教程文章与收藏 |
| 消息与评论 | [messaging](messaging.md) | 评论 / 私信 / 通知 / 横幅 |
| 审核系统 | [reviews](reviews.md) | 发布审核 / 意见反馈 / 举报案 |
| 招聘与加入 | [recruitment](recruitment.md) | 招生公告与加入流程 |
| 考试看板 | [exam-board](exam-board.md) | 批次 / 科目 / 误刊广播 |
| 关于页 | [about](about.md) | 关于页区块内容 |
| 校园全景图 | [panorama](panorama.md) | 全景图库、DJI 导入、分层取片 |
| 附件与上传 | [attachments](attachments.md) | 统一附件模型 + TUS 断点续传 |
| 公共 | [common](common.md) | 站点策略等公共接口 |

> 各模块文档中「认证」列的取值：**公开**（匿名可用）／**登录**（已登录）／**已验证**（登录且通过身份验证）／**职员**（持有相应权限）。
