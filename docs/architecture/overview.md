# 架构总览

> 前端内部结构见 [frontend.md](frontend.md)；环境搭建见 [快速开始](../getting-started.md)；生产部署见 [部署与运维](../operations/deployment.md)。

南汇一中传媒社的社团管理系统是一个**单体 Django 应用**：同一进程对外提供 REST API（Django REST Framework）、Django Admin、WebSocket 实时推送（Django Channels）以及 React SPA 的托管与静态资源。生产形态为 Nginx + Gunicorn（ASGI / UvicornWorker）+ systemd：缺省单 worker + SQLite（[ADR-0015](../adr/0015-channels-without-redis.md)），可选 PostgreSQL + Redis 频道层并提高 worker 数（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)）。

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 / 框架 | Python 3.14 · Django 6.0 |
| API | Django REST Framework（会话认证） |
| 实时 | Django Channels（缺省 InMemory 通道层；可选 Redis 频道层 + 多 worker） |
| 数据库 | SQLite 缺省（`db.sqlite3`）；可选 PostgreSQL |
| 前端 | React 19 · TypeScript · Webpack 5；产物 `frontend/dist/` 由 Django 托管 |
| 部署 | Nginx（一层反向代理）· Gunicorn ASGI · systemd |
| 外部集成 | SurveyJS（问卷）· Cloudflare Turnstile（人机验证）· Tiptap（富文本）等 |

## 请求生命周期

```
浏览器 ──Nginx──▶ Gunicorn(ASGI) ──▶ Django
   ├─ HTTP：中间件链 → URLconf → 视图（DRF ViewSet / 函数视图）
   │        → 权限与可见性判定 → ORM（SQLite / PostgreSQL）→ JSON 响应
   ├─ WebSocket：AuthMiddlewareStack → consumer（messaging / exam_board）
   └─ 其它路径：回落到 index.html（前端 HashRouter 自行路由）
```

### 中间件链（顺序即行为）

1. `MaintenanceModeMiddleware` —— 维护旗标；开启时全站 503，不触达数据库与会话
2. Django 标准件：安全 → 会话 → CORS → Locale → Common → CSRF → 认证 → Messages → X-Frame-Options
3. `PasswordChangeRequiredMiddleware` —— 管理员重置密码后的强制改密闸门（只放行改密 / 自身状态 / 登出 / 静态资源）
4. `MultiDeviceSessionMiddleware` —— 多端登录：最多 3 台设备同时在线，第 4 台顶掉最久未活动的那台（[ADR-0028](../adr/0028-multi-device-login.md)）
5. `LoginThrottleMiddleware` —— 登录保护与节流
6. `TusMiddleware` —— TUS 可续传上传的请求头解析

（实现见 `accounts/middleware.py`、`common/middleware.py`。）

### URL 挂载点

| 挂载 | 内容 | 文档 |
|---|---|---|
| `/admin/` | Django Admin 管理后台 | [管理后台指南](../operations/admin-guide.md) |
| `/site-policy/` | 站点策略公开投影 | [common](../api/common.md) |
| `/auth/` | 账号、登录、认证、资料 | [accounts](../api/accounts.md) |
| `/tasks/` `/messaging/` `/activities/` `/exam_board/` `/news/` `/reviews/` `/about/` `/tutorials/` `/recruitment/` `/attachments/` | 各业务模块 API | 各模块文档 |
| `/uploads/` | TUS 断点续传端点 | [attachments](../api/attachments.md) |
| `/file/…` | 公开媒体文件服务 | — |
| 未匹配路径（除已知前缀） | 回落 SPA 入口 `index.html` | [frontend](frontend.md) |

### WebSocket 路由

`/ws/messaging/`（登录：评论 / 私信 / 通知）与 `/ws/exam-board/`（公开：误刊广播）经 `AuthMiddlewareStack` + Origin 校验接入（见 `config/asgi.py`）。缺省 InMemory 通道层意味着**实时推送只在本进程内有效**——提高 worker 数前必须先引入 Redis（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)）。

## 模块地图（Django Apps）

| App | 职责 | 关键概念 | 参考 |
|---|---|---|---|
| `accounts` | 账号、登录 / 会话、身份认证、社员身份编号、安全验证、账号安全中心、资料与头像 | 多端登录（3 台）、登录保护、陌生设备挑战、滚动密钥、登录事件、能力投影 `can_*` | [API](../api/accounts.md) · [访问控制](../guides/access-control.md) · [账号与安全](../guides/account-security.md) |
| `common` | 站点策略、维护模式 | `SiteSettings` 运行时策略 | [API](../api/common.md) |
| `news` | 社团新闻 | 发布审核门控 | [API](../api/news.md) |
| `activities` | 活动（众议 / 征集 / 展示 / 调研） | 生命周期、复审、问卷绑定 | [API](../api/activities.md) · [问卷指南](../guides/surveys.md) |
| `tasks` | 任务与标签 | 状态机（`lifecycle.py`） | [API](../api/tasks.md) |
| `tutorials` | 教程文章 | 收藏 | [API](../api/tutorials.md) |
| `messaging` | 评论、私信、通知、横幅、禁言 | 评论区三态、WebSocket 推送 | [API](../api/messaging.md) |
| `reviews` | 审核系统 | 发布审核 / 意见反馈 / 举报案 | [API](../api/reviews.md) · [审核指南](../guides/moderation.md) |
| `recruitment` | 招生与加入 | 公告、加入问卷 | [API](../api/recruitment.md) |
| `exam_board` | 考试看板 | 批次 / 科目、误刊广播 | [API](../api/exam-board.md) |
| `about` | 关于页 | 区块内容 | [API](../api/about.md) |
| `attachments` | 统一附件与上传 | TUS、私有媒体 | [API](../api/attachments.md) |
| `panorama` | 校园全景图库 | DJI 导入、分层切片、多级浏览 | [API](../api/panorama.md) · [ADR-0022](../adr/0022-campus-panorama-library.md) |
| `announcements` | 全站弹窗公告 | 原件保真渲染（PDF / .docx）、受众、已读台账 | [API](../api/announcements.md) · [ADR-0042](../adr/0042-site-wide-popup-announcement.md) |

## 横切机制

### 访问控制：角色能力 = 权限

- 全部访问控制以 Django `Permission` + `has_perm` 为**唯一**判定轴；绝不检查分组名；`is_superuser` 是唯一应用访问逃生舱（`is_staff` 仅表示可登录 Admin）。
- 读默认走「身份 + 可见性」（`accounts/visibility.py`），敏感读才使用专门 `view_*` 权限。
- 前端消费服务端算好的语义化 `can_*` 布尔，不接触原始权限代号。
- 详见 [访问控制指南](../guides/access-control.md) 与 [ADR-0005](../adr/0005-access-control-principle.md)。

### 身份认证

- 登录后需通过身份认证（邮箱 / 人工审核 / 委任 / 认证码通道：见 [ADR-0006](../adr/0006-verification-model.md)、[ADR-0013](../adr/0013-appointment-verification-channel.md)、[ADR-0020](../adr/0020-authcode-verification-channel.md)）才计为正式「用户」；门禁分级：公开 → 登录 → 已认证 → 权限。
- 详见 [身份认证指南](../guides/certification.md)。

### 多端登录与登录保护（[ADR-0028](../adr/0028-multi-device-login.md)）

- 一个账号最多 **3 台设备同时保持登录态**（`UserSession.revoked_at IS NULL`）。名额满时新登录
  自动顶掉「最久未活动」的那台，被顶设备下次请求收到 `session_superseded` +
  `revoked_reason=limit`（见 [API 总览](../api/README.md#错误格式)）。
- 下线途径：本机主动退出（只下线本机）、个人中心「登录设备」手动下线单台 / 下线其他所有设备、
  安全事件（停用 / 重置密码 / 撤销认证 / 注销）一次性吊销全部设备。
- 登录保护改为**同账号 10 分钟内最多 5 次成功登录**（`login_protection`），三端依次登录不再互相阻塞。

### 账号安全中心（[ADR-0029](../adr/0029-account-security-center.md)）

- 页面 `/#/security`：登录方式（密码 / 邮箱 / 安全问题 / 通行密钥 / 滚动密钥 / 恢复代码）、设备列表、登录记录与城市地图。
- **设备信任只由二次验证写入**（`AccountDevice.trusted_at`）：陌生设备登录先返回 202 + 挑战（TOTP / 邮箱码 / 安全问题 / 恢复代码），通过后才建立会话；没有任何 2FA 的账号本次豁免（`must_bind_2fa`），设备保持陌生。`LOGIN_CHALLENGE=0` 可应急关闭挑战。
- 登录事件（`LoginEvent`）记录成功 / 失败 / 被限流 / 待验证；位置由离线 ip2region 解析到**城市级**，地图 key 走构建期 `AMAP_KEY`，无 key 时降级文字。
- 管理端三张只读表：登录事件、账号设备、管理端访问记录；查看行为写 `AdminAccessLog` 留痕。

### 审核轴（正交）

- 发布审核、意见反馈、举报案构成统一的审核系统：**只门控「公开展示」，不改变对象自身的业务状态**（正交轴设计，见 [ADR-0017](../adr/0017-unified-moderation-system.md) 与 [审核指南](../guides/moderation.md)）。

### 站点策略

- 注册开关、上传上限、节流速率等运行时可调策略存于 `common.SiteSettings`，经 `get_policy()` 快照供各视图读取（见 [ADR-0010](../adr/0010-runtime-site-policy.md)）；公开投影为 `/site-policy/`。

### 附件与文件存储

- 全站图片 / 文件引用统一走附件模型（[ADR-0001](../adr/0001-unified-attachment-nullable-fks.md)、[ADR-0002](../adr/0002-unified-attachment-endpoint-and-permission.md)）；大文件走 TUS（[ADR-0004](../adr/0004-feedback-media-tus-resumable-upload.md)）。
- 公开媒体在数据根的 `media/` 下（缺省即安装目录；统一数据根见 [data-root](../operations/data-root.md)）；**私有媒体**（身份证明等审计材料）在 `private_media/`，不经任何公开 URL 暴露。

## 数据与存储

- 数据库：缺省 SQLite（`db.sqlite3`），可切 PostgreSQL（`DB_ENGINE=postgresql`，[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)）；业务数据与会话均存于此。
- 静态资源：`frontend/dist/`（webpack 产物，构建时生成）与 `static/`，经 `collectstatic` 汇总到 `staticfiles/`。

## 部署形态

Nginx（一层代理）→ Gunicorn ASGI（worker 数由 `GUNICORN_WORKERS` 控制，缺省 1）· systemd 托管；更新与备份流程见 [部署与运维](../operations/deployment.md)。

## 设计记录

- 全部架构决策记录见 [docs/adr/](../adr/)（0001–0029、0041–0043）。
- 领域术语与项目概览：仓库根目录 [CONTEXT.md](../../CONTEXT.md)。
