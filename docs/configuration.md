# 配置参考

本项目的配置分三层，改任何一项前先确认它属于哪一层：

| 层 | 位置 | 生效方式 | 典型内容 |
|---|---|---|---|
| 进程环境变量 | `.env`（模板 `.env.example`，`.env` 已 gitignore） | 进程启动时读取，**改完必须重启** | 密钥、SMTP 授权码、Turnstile secret、域名、自动更新 token |
| Django settings | `config/settings.py` | 代码内，含从环境变量派生的默认值 | 数据库、静态文件、CORS/CSRF、中间件、DRF 全局配置 |
| 运行时站点策略 | `SiteSettings` 单例（Django admin 编辑），经 `GET /site-policy/` 下发 | 存 DB，改完即时生效（`save()` 失效缓存） | 限流额度、上传上限、评论/私信开关、自动更新窗口 |

第三层**不**是环境变量：运营旋钮走 DB，密钥与基础设施走 `.env`（设计记录 `docs/adr/0010-runtime-site-policy.md`）。下文按层展开。

## 一、环境变量（`.env.example` 全部条目）

复制模板开始：`cp .env.example .env`。生产由 `scripts/install.sh` 就位（它会写 `SECRET_KEY`、`FRONTEND_URL`、`ALLOWED_HOSTS`、`DJANGO_DEBUG=0`）；`start.sh` 在 `.env` 缺失时会自动从模板复制一份，然后 `set -a; . ./.env` 导出给 Gunicorn/Django。

| 变量 | 用途 | 必填 | 默认 / 示例 |
|---|---|---|---|
| `SECRET_KEY` | Django 签名密钥（session cookie、密码重置 token 等） | 生产必填 | 空。留空且 `DEBUG` 开时回退 `settings.py` 里的公开占位；`DJANGO_DEBUG=0` 且留空则 **拒绝启动**（`ImproperlyConfigured`） |
| `DJANGO_DEBUG` | 调试模式开关 | 否 | `1`（开）。生产务必设 `0` / `false`；取值 `1/true/yes/on`（不区分大小写）为真 |
| `ALLOWED_HOSTS` | 允许的 Host 头，逗号分隔 | 生产必填 | 空 → `[]`（本地由 DEBUG 兜底）。示例：`media-club.example.com,api.example.com` |
| `FRONTEND_URL` | 前端来源，用于拼接发给用户的邮件链接（邮箱验证、密码重置） | 生产建议填 | `http://localhost:3000`。示例：`https://media-club.example.com` |
| `EMAIL_HOST_USER` | 163 邮箱账号；**配了就切到 SMTP 后端** | 否 | 空。留空 → dev 用 console 后端（邮件打印到终端） |
| `EMAIL_HOST_PASSWORD` | 163 邮箱的「SMTP 授权码」（不是登录密码） | 配了 `EMAIL_HOST_USER` 就必填 | 空 |
| `TURNSTILE_SITE_KEY` | Cloudflare Turnstile 站点公钥；经 `GET /site-policy/` 下发给前端 | 否 | 空。两项都空 = 关闭人机校验；**都填了才启用**（只填一半视为关闭） |
| `TURNSTILE_SECRET_KEY` | Turnstile 服务端密钥（保密，永不下发） | 否 | 空 |
| `UPDATE_GITHUB_TOKEN` | GitHub PAT，需能读该仓库 Releases（自动更新守护进程用） | 生产必填 | 空 |
| `UPDATE_GITHUB_REPO` | 更新来源仓库，`owner/repo` | 否 | `nhyzcms/club-management-website`（留空也回退到该值） |
| `DB_ENGINE` 等 `DB_*` | 数据库切换与连接项：`DB_ENGINE=postgresql` 时用 PostgreSQL（`DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT`） | 否 | 全部留空 = SQLite（缺省）；示例 `DB_ENGINE=postgresql`、`DB_NAME=club` |
| `REDIS_URL` | 缓存 + Channels 频道层一并切到 Redis；多 worker 的前置条件 | 否 | 留空 = v1 行为（内存通道层、本地缓存、单 worker） |
| `GUNICORN_WORKERS` | ASGI worker 进程数 | 否 | `1`；**只有配了 `REDIS_URL` 才允许 >1** |
| `NOTIFICATIONS_DELIVERY_ASYNC` | 通知外发投递模式：默认异步（进程内队列 + 守护线程；失败退避自动重试）；`=0` 回退旧同步投递 | 否 | 留空 = 异步（默认）。示例 `NOTIFICATIONS_DELIVERY_ASYNC=0` |
| `CLUB_UPDATER_PROXY` / `CLUB_UPDATER_NO_PROXY` | 更新器出站代理（只注入更新守护进程，加速 GitHub API/Release 下载） | 否 | 空 = 不注入；示例 `CLUB_UPDATER_PROXY=http://127.0.0.1:7891` |
| `CLUB_DATA_DIR` | 统一数据根：媒体等持久数据的存放位置（`MEDIA_ROOT` / `PRIVATE_MEDIA_ROOT` 由它派生） | 否 | 空 = 安装目录（历史布局，行为不变）；示例 `<安装目录>/data`。见[统一数据根](../operations/data-root.md) |

注意事项：

- `.env` 不入库（`.gitignore` 已忽略），生产需 `chmod 600`。
- `SECRET_KEY` 生成：`python -c "import secrets;print(secrets.token_urlsafe()"`（模板注释给的命令；`scripts/install.sh` 用 `secrets.token_urlsafe(48)`）。
- 模板里 `SECRET_KEY=` 是**空字符串**，而 `os.environ.get` 会把「键存在但为空」当成已设置——`config/settings.py::_secret_key()` 专门处理这种情况：空 / 纯空白视为未设置，DEBUG 下回退占位、生产直接报错。`config/tests.py::SettingsHygieneTest` 有对应断言。
- `UPDATE_GITHUB_TOKEN` / `UPDATE_GITHUB_REPO` 也支持 `GITHUB_TOKEN` / `GITHUB_REPO` 作为 `install.sh` 的入参别名。
- 新增的 `DB_*` / `REDIS_URL` / `GUNICORN_WORKERS` 遵守「缺省中性」：全部留空时行为与 v1 完全一致，开与关只动 `.env`（见 [ADR-0021](adr/0021-postgresql-redis-and-multiworker.md)）。
- `CLUB_DATA_DIR` 同样「缺省中性」：缺省 = 安装目录 → 历史布局；媒体路径全部由它派生，启用统一数据根（或换盘 / 换位置）只需改这一个键。

### 其他环境变量（不在 `.env.example`，代码中真实读取）

| 变量 | 读取位置 | 用途 |
|---|---|---|
| `DJANGO_TESTING` | `config/settings.py` | 置 `1` 时等价于「正在跑测试」，启用测试期提速设置（见下文 §2.8） |
| `DJANGO_DB_FILE` | `config/settings.py` | 数据库文件路径覆盖；E2E 经 `scripts/e2e-server.sh` 置为独立库 `run/e2e.sqlite3`（每次重建），缺省 `db.sqlite3` |
| `CLUB_SPAWN_UPDATER` | `start.sh` | 置 `0` 时不拉起更新守护进程（排障只起 web） |
| `CLUB_UPDATER_SPAWNED` | `start.sh` / `common/updater.py` | 由 `start.sh` 置 `1`，标记更新进程由 web 拉起；apply 时据此对 Gunicorn 父进程发 SIGHUP 而不是 `systemctl restart` |
| `SERVICE_NAME` | `common/updater.py` | systemd unit 名，默认 `club` |

## 二、Django settings（`config/settings.py`）

### 2.1 核心与安全

| 设置 | 值 / 逻辑 | 说明 |
|---|---|---|
| `TESTING` | `"test" in sys.argv or DJANGO_TESTING == "1"` | 仅据此切换「测试期才该变」的设置，绝不影响 runserver / 生产 |
| `DEBUG` | `DJANGO_DEBUG` 默认 `1` | 见环境变量表 |
| `SECRET_KEY` | `_secret_key(env, debug=DEBUG)` | 空值处理见上；DEBUG 回退 `_DEV_SECRET_KEY` |
| `ALLOWED_HOSTS` | `_parse_allowed_hosts(env)` | 逗号分隔 → list，逐项 strip，空项丢弃 |
| `SECURE_PROXY_SSL_HEADER` | `("HTTP_X_FORWARDED_PROTO", "https")` | nginx 写 `X-Forwarded-Proto`；HSTS 与 `is_secure()` 靠这一条认出 HTTPS。客户端自带的该头由 nginx `proxy_set_header` 覆盖 |
| `SECURE_HSTS_SECONDS` | `_https_security(DEBUG)`：debug 时 `0`，生产 `31536000` | 生产开 HSTS 1 年；不含 `includeSubDomains` / `preload`。`SecurityMiddleware` 只在 `is_secure()` 时下发，本地 HTTP 不受影响 |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | 同上：debug `False`，生产 `True` | 值在 import 时钉死（Django 测试 runner 会把 `DEBUG` 改成 `False`，但不会重算这些） |
| `X_FRAME_OPTIONS` | `"SAMEORIGIN"` | Django 默认 `DENY` 会让 Chrome 把同源 admin 预览 iframe 渲染成「拒绝连接」；`SAMEORIGIN` 仍挡第三方点击劫持，只允许本站嵌入自己的页面（审核对象界面） |
| `LOGIN_URL` | `"/login/"` | |
| `FRONTEND_URL` | 环境变量，默认 `http://localhost:3000` | 拼邮件链接用 |
| `LANGUAGE_CODE` / `TIME_ZONE` | `zh-hans` / `UTC` | `USE_I18N = True`，`USE_TZ = True` |

### 2.2 应用与中间件

`INSTALLED_APPS` 顺序（`daphne` 置首以接管 `runserver`）：

```text
daphne, django.contrib.{admin,auth,contenttypes,sessions,messages,staticfiles},
corsheaders, rest_framework, django_filters, channels,
common, accounts, about, tasks, messaging, activities, exam_board,
news, reviews, tutorials, recruitment, attachments, rest_framework_tus
```

`MIDDLEWARE`（自上而下，顺序有意义）：

| 中间件 | 说明 |
|---|---|
| `common.middleware.MaintenanceModeMiddleware` | 维护旗标 `run/MAINTENANCE` 存在时返回 503 HTML；不碰 DB / session，**必须**先于 Session/CSRF/Tus |
| `django.middleware.security.SecurityMiddleware` | HSTS 等安全头 |
| `django.contrib.sessions.middleware.SessionMiddleware` | Session 认证基础 |
| `corsheaders.middleware.CorsMiddleware` | 见 2.4 |
| `django.middleware.locale.LocaleMiddleware` | |
| `django.middleware.common.CommonMiddleware` | |
| `django.middleware.csrf.CsrfViewMiddleware` | |
| `django.contrib.auth.middleware.AuthenticationMiddleware` | |
| `accounts.middleware.ValidityEnforcementMiddleware` | 身份有效期惰性执行（响应后、按会话节流 300 秒；须在 AuthenticationMiddleware 之后） |
| `django.contrib.messages.middleware.MessageMiddleware` | |
| `django.middleware.clickjacking.XFrameOptionsMiddleware` | |
| `accounts.middleware.SingleSessionMiddleware` | 单会话（挤号）；内容协商：浏览器导航给 HTML 页，SPA/API 给 JSON 契约 |
| `accounts.middleware.LoginThrottleMiddleware` | 登录失败限流（额度来自站点策略） |
| `rest_framework_tus.middleware.TusMiddleware` | 解析 `Tus-*` / `Upload-*` 请求头到 `request` 属性 |

`ROOT_URLCONF = "config.urls"`；`WSGI_APPLICATION = "config.wsgi.application"`；`ASGI_APPLICATION = "config.asgi.application"`。

### 2.3 模板、ASGI 与 Channels

| 设置 | 值 | 说明 |
|---|---|---|
| `TEMPLATES[0]["DIRS"]` | `[BASE_DIR / "frontend" / "dist"]` | 直接渲染 webpack 产物 `index.html` |
| `CHANNEL_LAYERS` | 缺省 `InMemoryChannelLayer`；配 `REDIS_URL` 后为 `channels_redis`（前缀 `club`） | 未配 Redis 时保持单进程（ADR 0015）；配好 Redis 频道层后可用 `GUNICORN_WORKERS` 提高（ADR 0021） |
| `CACHES` | 配 `REDIS_URL` 时为 `RedisCache`（前缀 `club`）；否则 Django 默认本地内存缓存 | 站点策略 / 限流缓存跨 worker 一致性的前置条件 |

`config/asgi.py` 用 `ProtocolTypeRouter` 分派：`http` / `lifespan` → Django ASGI 应用，`websocket` → `AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(...)))`。WebSocket 路由为 `messaging` + `exam_board` 两组拼接（`/ws/messaging/` 需登录，`/ws/exam-board/` 匿名可连）。

### 2.4 数据库 / 静态 / 媒体

| 设置 | 值 | 说明 |
|---|---|---|
| `DATABASES` | 缺省 SQLite（`NAME` 取 `DJANGO_DB_FILE`，缺省 `BASE_DIR / "db.sqlite3"`）；`DB_ENGINE=postgresql` 时切 PostgreSQL（`DB_*` 连接项、`CONN_MAX_AGE=60` + 健康检查） | 缺省单文件已 gitignore；PG 为生产可选升级（ADR 0021），迁移见 deployment.md §7 |
| `STATIC_URL` | `static/` | |
| `STATIC_ROOT` | `BASE_DIR / "staticfiles"` | `collectstatic` 输出（生产由 nginx 服务） |
| `STATICFILES_DIRS` | `[frontend/dist, static]` 中**存在**的目录 | `frontend/dist` 是 webpack 产物（gitignored）；目录缺失时自动跳过，保证全新 clone 跑测试不触发 `staticfiles.W004` |
| `DATA_DIR` | `CLUB_DATA_DIR` 环境变量；缺省 `BASE_DIR`，相对值按 `BASE_DIR` 锚定 | 统一数据根（见[统一数据根](../operations/data-root.md)）；下列媒体路径全部由它派生 |
| `MEDIA_URL` / `MEDIA_ROOT` | `/media/` / `DATA_DIR / "media"` | 公开用户上传（头像等）。注意 DEBUG 下 `config/urls.py` 会用 `static(MEDIA_URL)` 公开服务整个 `MEDIA_ROOT` |
| `PRIVATE_MEDIA_ROOT` | `DATA_DIR / "private_media"` | 私有媒体（身份证明等审计留底），**必须落在 `MEDIA_ROOT` 之外**，由带鉴权的视图服务；有测试断言其隔离性 |

### 2.5 CORS / CSRF

| 设置 | 值 | 说明 |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000`、`http://127.0.0.1:3000` | 硬编码的开发态来源；生产为同源部署（Django 直接托管前端），不需要额外来源 |
| `CORS_ALLOW_CREDENTIALS` | `True` | 允许携带 Cookie（session 认证依赖） |
| `CORS_ALLOW_HEADERS` | `corsheaders.defaults.default_headers` + `x-device-id` | `X-Device-Id` 由前端 `utils/deviceId.ts` 生成（访客问卷去重与统计） |
| CSRF | Django 默认 `CsrfViewMiddleware` + `csrftoken` Cookie | 前端启动时显式 `GET /auth/csrf/`（`@ensure_csrf_cookie`）拉取 Cookie——dev 态 webpack 直接服务模板、不经 Django 渲染，无法依赖 `{% csrf_token %}` 下发 |

### 2.6 邮件 / Turnstile / 自动更新

| 设置 | 逻辑 |
|---|---|
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | 直接来自环境变量 |
| `EMAIL_BACKEND` | `_email_backend_for(EMAIL_HOST_USER)`：非空 → `smtp.EmailBackend`，空 → `console.EmailBackend` |
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_USE_SSL` | 配了 `EMAIL_HOST_USER` 才设：`smtp.163.com` / `465` / `True` |
| `DEFAULT_FROM_EMAIL` | 配了 SMTP 时为 `EMAIL_HOST_USER` |
| `NOTIFICATIONS_DELIVERY_ASYNC` | 环境变量；默认开。异步 = 进程内队列 + 守护线程消费（`messaging/notifications/queue.py`，失败退避重试，见 [ADR-0024](adr/0024-async-notification-delivery.md)）；`=0` 回退旧同步投递。测试期默认同步（用例可 `override_settings` 开启） |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | 环境变量，默认空。两项都非空才启用（`accounts/turnstile.py::is_turnstile_enabled()`）；启用后 sitekey 经 `GET /site-policy/` 下发，secret 只留进程内 |
| `UPDATE_GITHUB_TOKEN` / `UPDATE_GITHUB_REPO` | 环境变量；repo 默认 `nhyzcms/club-management-website`（空串也回退）。窗口 / 轮询等旋钮在 `SiteSettings` |

### 2.7 DRF 与 tus

| 设置 | 值 |
|---|---|
| `DEFAULT_AUTHENTICATION_CLASSES` | `rest_framework.authentication.SessionAuthentication`（无 JWT） |
| `DEFAULT_PERMISSION_CLASSES` | `rest_framework.permissions.IsAuthenticated` |
| `NUM_PROXIES` | `1` —— 一层 nginx，取 `X-Forwarded-For` 最右（真实客户端），忽略客户端伪造的前缀 |
| `DEFAULT_THROTTLE_RATES` | `{}` —— 运营限流额度住在 `SiteSettings`（`get_policy()`），各限流类覆写 `get_rate()` 直接读快照，**不读**这个 map。限流类：`accounts/throttles.py` 的 `RegisterThrottle` / `ResendVerificationThrottle` / `LoginIpThrottle` / `LoginUsernameThrottle`，`reviews/throttles.py` 的 `FeedbackAnonThrottle` / `ReportDailyThrottle` |
| `DEFAULT_PAGINATION_CLASS` / `PAGE_SIZE` | `PageNumberPagination` / `20` |
| `DEFAULT_FILTER_BACKENDS` | `DjangoFilterBackend` + `SearchFilter` + `OrderingFilter` |
| `REST_FRAMEWORK_TUS["MAX_FILE_SIZE"]` | `500 * 1024 * 1024`（库级兜底；实际上限读 `get_policy().tus_media_max_bytes`） |
| `REST_FRAMEWORK_TUS["TUS_UPLOAD_DESTINATION"]` | `tus_uploaded`（相对 `MEDIA_ROOT`） |
| `REST_FRAMEWORK_TUS["UPLOAD_MODEL"]` | `attachments.TusUpload`（自定义模型，补 `user` 外键） |
| 其他 tus 默认 | 临时分片 `BASE_DIR/tmp/uploads`，`UPLOAD_EXPIRES` 1 天 |

### 2.8 测试期提速（仅 `TESTING=True` 生效）

| 设置 | 值 | 原因 |
|---|---|---|
| `PASSWORD_HASHERS` | `["django.contrib.auth.hashers.MD5PasswordHasher"]` | 默认 PBKDF2 约 374ms/次；测试库每次清空、绝不进生产 |
| `EMAIL_BACKEND` | `django.core.mail.backends.locmem.EmailBackend` | 注册 / 验证 / 重置路径发信不触网、不阻塞，可断言 `mail.outbox`（防御性：本地 `.env` 若配了 SMTP 也会被切回内存后端） |

## 三、运行时站点策略（`SiteSettings`）

`common/models.py::SiteSettings` 是 pk 恒为 1 的单例，只在 Django admin 编辑（`verbose_name = "站点策略"`）；`save()` 会失效缓存键 `common.site_policy`。调用方一律经 `common/policy.py::get_policy()` 读快照，**不查模型**；无行 / DB 不可用时回退代码内默认值。`GET /site-policy/` 把快照 + Turnstile 公开字段一并下发给 SPA。

| 字段 | 默认值 | 作用 |
|---|---|---|
| `verification_enabled` | `True` | 验证通道总开关 |
| `verification_valid_days` | `365` | 认证有效期（天）：认证通过后的有效期，过期需重新认证 |
| `admin_valid_days` | `730` | 管理员身份有效期（天）：过期自动撤销 `is_staff`；超管不受限 |
| `registration_verify_days` | `60` | 注册后验证宽限（天）：超期未认证自动停用 |
| `content_review_enabled` | `True` | 内容审核；关闭后新建内容直接通过 |
| `registration_enabled` | `True` | 自助注册；关闭后接口 403 |
| `register_per_ip_per_day` | `5` | 每 IP 每日注册次数 |
| `resend_verification_per_ip_per_hour` | `5` | 每 IP 每小时重发验证邮件次数 |
| `login_per_ip_per_hour` | `30` | 每 IP 每小时登录**失败**次数（门户与 admin 共用，只计失败） |
| `login_per_username_per_hour` | `10` | 每用户名 / 邮箱每小时登录失败次数 |
| `feedback_anon_per_ip_per_day` | `10` | 每 IP 每日匿名反馈次数 |
| `reports_per_user_per_day` | `10` | 每用户每日举报次数 |
| `authcode_redeem_per_user_per_hour` | `10` | 每账号每小时认证码兑换**失败**次数（只计失败） |
| `sync_upload_max_bytes` | `52428800`（50MB） | 同步上传单文件上限 |
| `tus_media_max_bytes` | `524288000`（500MB） | tus 图 / 视频上限 |
| `auto_update_enabled` | `True` | 自动更新总开关 |
| `update_poll_interval_seconds` | `900` | 轮询间隔 |
| `update_timezone` | `Asia/Shanghai` | IANA 时区名，不用 Django `TIME_ZONE` |
| `update_window_start_hour` / `update_window_end_hour` | `1` / `3` | 应用窗口 `[开始, 结束)` |
| `update_apply_cutoff_minutes_before_end` | `30` | 窗口结束前 N 分钟起不再开始应用 |
| `update_release_keep` / `update_db_backup_keep` | `3` / `5` | 保留发行包 / DB 快照份数 |
| `comments_enabled` / `comment_max_depth` | `True` / `8` | 评论区开关与最大嵌套深度（1 = 仅根评论） |
| `dms_enabled` | `True` | 私信开关 |

维护拦截是**文件旗标**而非 DB：`run/MAINTENANCE`（由 `manage.py maintenance on|off|status` 或更新守护进程写），中间件只读文件、绝不读 `SiteSettings`，避免 `migrate` 时死锁 SQLite。

## 四、前端构建配置

### 4.1 脚本（`frontend/package.json`）

| 脚本 | 内容 |
|---|---|
| `dev` | `node scripts/copy-surveyjs.js && webpack serve` |
| `build` | `webpack --mode production && node scripts/copy-surveyjs.js && node scripts/assert-live2d-dist.js && node scripts/assert-surveyjs-dist.js` |
| `copy-surveyjs` | `node scripts/copy-surveyjs.js` |

`copy-surveyjs.js` 把 SurveyJS 未哈希 min 文件（survey-core / creator / analytics / chart.js / 中文 i18n 共 11 个）同时拷入仓库根 `static/surveyjs/`（本地 runserver 供 admin 模板 `{% static 'surveyjs/...' %}` 引用）与 `frontend/dist/surveyjs/`（生产 collectstatic / 发布包）。升级 `survey-*` / Chart.js 后必须重跑。

### 4.2 webpack（`frontend/webpack.config.js`）

| 配置 | 值 | 说明 |
|---|---|---|
| `mode` | 配置文件写 `development` | 构建时由 CLI `--mode production` 覆盖 |
| `entry` | `./src/index.tsx` | 前端唯一入口 |
| `output.path` | `frontend/dist/` | |
| `output.filename` | `[name].[contenthash].js` | chunk 同理 `[name].[contenthash].chunk.js` |
| `output.publicPath` | `/static/` | 与 Django `STATIC_URL` 对齐 |
| `output.clean` | `true` | 每次构建清空 dist |
| `resolve.extensions` | `.ts .tsx .js .jsx` | |
| loader | `ts-loader`（`onlyCompileBundledFiles`）、`css-loader` + `style-loader` | TypeScript 由 webpack 编译，`frontend/tsconfig.json`：`target ES2020`、`strict: true`、`jsx: react-jsx` |
| `HtmlWebpackPlugin` | 模板 `./template.html`，favicon `./public/favicon.ico` | 生成 `dist/index.html` |
| `CopyWebpackPlugin` | `vendor/live2d/` → `dist/live2d` | 看板娘静态资源 |
| `optimization.splitChunks` | 三层 cacheGroups：`vendor`（同步首屏库，排除 `l2d`）、`asyncVendor`（异步共享库 ≥2 页）、`default`（应用代码 ≥2 次复用）；`defaultVendors` 关闭、`minSize` 20KB | 重库不进首屏、随页面按需加载；看板娘运行时单独成块 |
| `devServer.port` / `hot` | `3000` / `true` | HMR |
| `devServer.historyApiFallback.index` | `/static/index.html` | SPA 兜底 |
| `devServer.proxy` | 两条规则 | WebSocket：`/ws/messaging`、`/ws/exam-board`（`ws: true`）；HTTP：`/auth`、`/admin`、`/media`、`/tasks`、`/messaging`、`/news`、`/attachments`、`/uploads`、`/activities`、`/reviews`、`/about`、`/exam_board`、`/tutorials`、`/recruitment`、`/site-policy` —— 目标均为 `http://localhost:8000` |

**环境差异如何抹平**：webpack 配置里**没有** `DefinePlugin`，`frontend/src/` 里也**没有**任何 `process.env` 读取。开发态与生产态的差异全部靠两点消化：① 所有请求走相对路径 + `/static/`、`/media/` 前缀；② 开发态由 `devServer.proxy` 把后端前缀转发到 `:8000`，生产态由 nginx / Django 直接服务同一批路径。因此新增后端 API 前缀时，`devServer.proxy` 的清单与 `config/urls.py` 的 catch-all 排除清单必须**两处同步登记**。

### 4.3 构建产物与断言

`frontend/dist/`（gitignored，由 Django 的 `TEMPLATES["DIRS"]` 与 `STATICFILES_DIRS` 引用）大致含：`index.html`、入口与懒加载 `*.chunk.js`、`vendor.*.js`、`live2d/`、`surveyjs/`、`favicon.ico`。

`npm run build` 末尾的两个断言脚本是前端唯一的自动质量关口（缺文件即构建失败）：

| 脚本 | 断言内容 |
|---|---|
| `assert-live2d-dist.js` | `dist/live2d/` 下 runtime / widget / `catalog.json` 共 8 项齐全；`catalog.json` 为合法 JSON、`version === 1`、`models` 非空且每项有 `id` 与 `entry`，且 `entry` 指向的文件确实存在；至少拷入一份 LICENSE 文本 |
| `assert-surveyjs-dist.js` | `dist/surveyjs/` 下 11 个未哈希 min 文件齐全 |

CI 另外断言 `frontend/dist/surveyjs/survey.core.min.js` 存在（`.github/workflows/ci.yml` 的 `frontend` job）。

## 五、改配置的常见路径

| 想改什么 | 改哪里 | 生效方式 |
|---|---|---|
| 密钥 / 域名 / SMTP / Turnstile / 更新 token | `.env` | 重启进程（生产 `sudo systemctl restart club`） |
| 数据库 / Redis / worker 数 | `.env`（`DB_*` / `REDIS_URL` / `GUNICORN_WORKERS`） | 重启进程；数据迁移与回滚见 deployment.md |
| 限流额度、上传上限、评论 / 私信开关、验证有效期、更新窗口 | Django admin「站点策略」 | 即时（`save()` 失效缓存） |
| 全站维护拦截 | `uv run python manage.py maintenance on --message "..."` | 即时（文件旗标，无需重启） |
| CORS 来源、DRF 全局配置、中间件、分页大小 | `config/settings.py` | 改代码 + 重启 |
| 前端构建行为 | `frontend/webpack.config.js` / `package.json` / `tsconfig.json` | 重新 `npm run build` |

`config/tests.py::SettingsHygieneTest` 钉住了若干结构不变量：限流额度不得回到 `REST_FRAMEWORK`、`NUM_PROXIES == 1`、私有媒体与公开 `MEDIA_ROOT` 隔离、媒体路径统一派生自 `DATA_DIR`、邮件后端选择函数的分支、`.env.example` 必须入库且含全部必要键。改动上述配置时这些测试会给出反馈。
