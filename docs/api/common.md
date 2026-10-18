# 公共 API（站点策略与站点级行为）

`common` app 提供的站点级公共能力：唯一的公开端点 `GET /site-policy/`（运行时运营旋钮快照 + Turnstile 公开字段）、维护模式 503 拦截、`media/file/` 固定目录的公开服务，以及旋钮的 admin 编辑路径。`common` 自身没有 `urls.py`——`site-policy` 与 `file` 均由 `config/urls.py` 直接挂载。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0010](../adr/0010-runtime-site-policy.md)

## 模块约定

- **挂载位置**：`GET /site-policy/`（`SitePolicyView`，name=`site-policy`，无 app 前缀）；`GET /file/{path}`（`re_path` + `django.views.static.serve`，`document_root = BASE_DIR/media/file`）。
- **策略快照（`common/policy.py`）**：运营旋钮住 `SiteSettings` 单例（pk 恒 1），调用方一律经 `get_policy()` 读，**不查模型**；快照按缓存键 `common.site_policy` 缓存（`timeout=None`，`SiteSettings.save()` 时失效），`SiteSettings` 无行 / DB 不可用时回退到代码内默认值（与字段默认值一致，行为中立）。加旋钮 = 新字段 + 迁移 + 快照字段，不做通用 KV 袋。
- **密钥与基础设施**（`SECRET_KEY`、SMTP、Turnstile secret、`FRONTEND_URL`、MEDIA 路径）仍在 `config/settings.py` + `.env`，改完需重启；**secret 永不下发**。
- **认证**：`/site-policy/` 为 `AllowAny` 且 `authentication_classes = []`——匿名 GET，不碰 session / CSRF；`/file/{path}` 亦无鉴权。
- **写入路径**：旋钮只走 Django admin（`is_staff` + `change_sitesettings`，单例、禁增删、changelist 直接跳表单）；无产品侧写接口。维护旗标走 `manage.py maintenance on|off` 与自动更新守护进程。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | `/site-policy/` | 公开 | — | 站点策略快照 + Turnstile 公开字段 |
| GET | `/file/{path}` | 公开 | — | `media/file/` 目录静态服务 |

## 端点详情

### 站点策略快照

`GET /site-policy/`

**认证**：公开（`AllowAny`，且显式关闭认证类）；**权限**：—。SPA 启动时拉取一次；前端在不可达时回退到内置默认值。

**响应 `200 OK`**（示例为默认值）

```json
{
  "verification_enabled": true,
  "content_review_enabled": true,
  "registration_enabled": true,
  "register_per_ip_per_day": 5,
  "resend_verification_per_ip_per_hour": 5,
  "login_per_ip_per_hour": 30,
  "login_per_username_per_hour": 10,
  "feedback_anon_per_ip_per_day": 10,
  "reports_per_user_per_day": 10,
  "authcode_redeem_per_user_per_hour": 10,
  "sync_upload_max_bytes": 52428800,
  "tus_media_max_bytes": 524288000,
  "auto_update_enabled": true,
  "update_poll_interval_seconds": 900,
  "update_timezone": "Asia/Shanghai",
  "update_window_start_hour": 1,
  "update_window_end_hour": 3,
  "update_apply_cutoff_minutes_before_end": 30,
  "update_release_keep": 3,
  "update_db_backup_keep": 5,
  "comments_enabled": true,
  "comment_max_depth": 8,
  "dms_enabled": true,
  "verification_valid_days": 365,
  "admin_valid_days": 730,
  "registration_verify_days": 60,
  "turnstile_enabled": false,
  "turnstile_site_key": ""
}
```

`turnstile_enabled` / `turnstile_site_key` 来自 `.env`（`TURNSTILE_SITE_KEY` 与 `TURNSTILE_SECRET_KEY` **都非空**才启用；只配一半视为关闭），叠加在快照之上返回，**不在** `SiteSettings` 表内。未启用时 sitekey 为空串。

### 字段语义与消费者

| 字段 | 类型 | 默认 | 含义 / 消费方 |
|---|---|---|---|
| verification_enabled | bool | `true` | 认证通道总开关；关闭后不可新开 / 完成任何通道，已通过者仍算已认证。消费方：`accounts`（注册建通道、绑邮 / 换邮、人工提交、认证链接落地、身份审核通过 / 驳回） |
| content_review_enabled | bool | `true` | 内容审核总开关；关闭后新建新闻 / 活动 / 教程直接通过、不进待审队列（已有待审条目不批量通过）。消费方：`reviews.lifecycle` |
| registration_enabled | bool | `true` | 自助注册开关；关闭后注册返回 403。消费方：`accounts` 注册视图 |
| register_per_ip_per_day | int | `5` | 每 IP 每日注册次数上限（`accounts.throttles.RegisterThrottle`，校验前先限流） |
| resend_verification_per_ip_per_hour | int | `5` | 每 IP 每小时重发认证邮件次数（`ResendVerificationThrottle`；绑定邮箱与重发两条路径共用） |
| login_per_ip_per_hour | int | `30` | 每 IP 每小时**登录失败**次数（门户与 Django admin 共用；成功登录不占额度） |
| login_per_username_per_hour | int | `10` | 每用户名 / 邮箱每小时登录失败次数（防针对单一账号撞库） |
| feedback_anon_per_ip_per_day | int | `10` | 每 IP 每日匿名反馈次数（`reviews` 限流） |
| reports_per_user_per_day | int | `10` | 每用户每日举报次数（`reviews` 限流） |
| authcode_redeem_per_user_per_hour | int | `10` | 每账号每小时认证码兑换**失败**次数（`accounts.throttles.AuthCodeRedeemThrottle`；只计失败，成功不占额度） |
| sync_upload_max_bytes | int | `52428800`（50MB） | 同步上传单文件上限（任意类型）；超过则仅图片 / 视频可走 tus。消费方：`attachments` |
| tus_media_max_bytes | int | `524288000`（500MB） | tus 通路图 / 视频上限（`TusUploadViewSet.max_file_size`，admin 改后无需重启即生效） |
| auto_update_enabled | bool | `true` | 自动更新总开关；关闭后守护进程跳过下载与应用。消费方：`common.updater` |
| update_poll_interval_seconds | int | `900` | 更新轮询间隔（秒） |
| update_timezone | string | `Asia/Shanghai` | 应用窗口时区（IANA 名；不用 Django `TIME_ZONE`） |
| update_window_start_hour | int | `1` | 应用窗口开始时刻（整点小时，0–23） |
| update_window_end_hour | int | `3` | 应用窗口结束时刻（半开区间 `[开始, 结束)`；`开始 == 结束` 视为空窗口，起 > 止按跨夜处理） |
| update_apply_cutoff_minutes_before_end | int | `30` | 窗口结束前 N 分钟起不再开始应用更新 |
| update_release_keep | int | `3` | 保留发行包份数（超出按修改时间最旧清理，连同 `.sha256` 旁车） |
| update_db_backup_keep | int | `5` | 保留数据库快照份数（`backups/db-*.sqlite3` / `db-*.pg.sql`） |
| comments_enabled | bool | `true` | 评论区开关；关闭后前端不显示评论区且无法发新评论，已有评论保留。消费方：`messaging` |
| comment_max_depth | int | `8` | 评论最大嵌套深度（1–32；超深拒绝，不改挂） |
| dms_enabled | bool | `true` | 私信开关；关闭后不显示入口且无法发起 / 发送，已有会话保留。消费方：`messaging` |
| verification_valid_days | int | `365` | 认证有效期（天）：邮箱 / 人工 / 认证码通道通过后的有效期；到期后不再算已认证，需重新认证。消费方：`accounts`（通道通过时写 `expires_at`、`is_verified` 判定） |
| admin_valid_days | int | `730` | 管理员身份有效期（天）：后台委任通道的有效期；到期后系统撤销 `is_staff`。超级管理员不受限（永久）。消费方：`accounts`（委任通道、有效期执行） |
| registration_verify_days | int | `60` | 注册后认证宽限（天）：注册后从未认证、超期将停用账号；可被 `Profile.registration_deadline` 显式覆盖。消费方：`accounts`（有效期执行） |
| turnstile_enabled | bool | `false` | Turnstile 是否启用；前端据此挂载挂件。校验点：注册、找回密码、重发认证信（登录不校验）、未登录匿名反馈 |
| turnstile_site_key | string | `""` | 公开 sitekey（未启用时为空串；secret 永不下发） |

> 前端（`frontend/src/api/sitePolicy.ts`）内置同名默认值，`/site-policy/` 不可达时回退；`turnstile_enabled` / `turnstile_site_key` 用于挂载挂件并随请求带 `turnstile_token`。

### 调用示例

```bash
curl http://localhost:8000/site-policy/
curl -I http://localhost:8000/file/ClassIsland快速使用指南.pdf
```

`/site-policy/` 无缓存头、无 ETag；前端只在应用启动时拉一次，运行期以本地快照为准（旋钮改动后需刷新页面或等待下次启动）。服务端快照缓存走 Django cache 后端（缺省 `locmem` 进程内、不跨进程共享；配 `REDIS_URL` 后为 Redis、跨进程共享——[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)）——缺省后端下多 worker 时 admin 改旋钮只在当前进程即时生效，其余 worker 待缓存失效 / 重启后一致。

### `media/file/` 静态服务

`GET /file/{path}`

**认证**：公开；**权限**：—。`config/urls.py` 的 `re_path(r'^file/(?P<path>.*)$', serve, {'document_root': BASE_DIR/media/file})`：以 Django `static.serve` 直接服务固定目录 `media/file/` 下的文件（课表 YAML、工具包等运营上传物），不经附件权限体系、无鉴权。

**响应 `200 OK`**：文件字节流（`Content-Type` 由文件名推断）。**错误**：404 文件不存在或路径逃逸。

> 安全含义：写入 `media/file/` 即等于**公开可读**；不要放置含个人信息的材料（身份证明走 `PRIVATE_MEDIA_ROOT` + 鉴权下载，见[账号与认证 API](accounts.md)）。

## 站点级行为（非 `common` 端点，但由本模块承载）

### 维护模式 503

`common.middleware.MaintenanceModeMiddleware` 位于中间件链最前（先于 Session / CSRF / 认证）：只要旗标文件 `run/MAINTENANCE` 存在，**任何请求**都直接返回 503 HTML 维护页，跳过其余中间件与视图。

- 渲染不传 request（不碰 DB / session / CSRF / context processor），只用内联 CSS，不依赖 `frontend/dist`；响应带 `Cache-Control: no-store`。
- `Retry-After`：更新进行中（`reason=update`）为 `5`，运维拦截（`reason=ops`）为 `120`。
- 旗标文件即事实源（JSON，含 `reason` / `message` / `step` / `step_index` / `step_total` / `sha` / `resume_ops` / `ops_message`），中间件只读文件、不读 `SiteSettings`——避免 migrate 期间 SQLite 死锁。
- 更新时页面按 8 步展示进度（`drain` 拦截访问 → `backup` 备份数据库 → `unpack` 解包 → `sync` 替换文件 → `deps` 同步依赖 → `migrate` 迁移 → `collectstatic` 收集静态 → `reload` 重载服务；回滚另显示「正在回滚到上一版本」，进度百分比按 `step_index / step_total` 计算）。
- 运维入口：`manage.py maintenance on|off|status`。`on` 可带 `--message`（显示在维护页）；更新进行中执行 `on` 会记下 `resume_ops`，更新结束后自动恢复运维拦截；`off` 不会中止进行中的更新（只取消「结束后的运维拦截」）。
- 影响面：维护页对**全站**（含 `/admin/`）生效，API 客户端同样收到 503 HTML（非 JSON）。

### 自动更新守护进程

`common/updater.py`（由 `start.sh` 随 Gunicorn 拉起，同一 systemd cgroup）按 `update_poll_interval_seconds` 轮询 GitHub Release（`UPDATE_GITHUB_REPO`，默认 `nhyzcms/club-management-website`；token 走 `UPDATE_GITHUB_TOKEN`）。

- **预取**：下载 `club-{sha}.tar.gz` + `.sha256` 到 `backups/releases/`，支持断点续传（HTTP Range）、校验失败重下、最多 8 次指数退避重试；未完成的 `.part` 绝不参与应用。
- **应用条件**：`auto_update_enabled=true` 且处于应用窗口 `[update_window_start_hour, update_window_end_hour)`、距窗口结束还有 `update_apply_cutoff_minutes_before_end` 分钟以上；手动 `--apply-now` 跳过窗口判断。
- **应用流程**：写维护旗标 → 备份数据库快照（SQLite `backups/db-{时间戳}.sqlite3` / PostgreSQL `db-{时间戳}.pg.sql`，按 `update_db_backup_keep` 裁剪）→ 解包到临时 staging → 替换代码树（`.env` / `db.sqlite3` / `media` / `private_media` / `data` / `run` / `backups` / `.venv` 等排除在外）→ `uv sync --frozen` → `migrate` → `collectstatic` → 重载服务并健康检查；成功后记 `run/applied-release`、按 `update_release_keep` 裁剪发行包。
- **失败处理**：任一步失败或窗口关闭 → 自动回滚（恢复上一发行包代码树 + 应用前的数据库快照 + 重载），回滚后服务不健康则保留维护页。
- 手动回滚（`--rollback`，可指定 SHA / tag / 本地包）：只换代码树、**不动站点数据**——与应用失败时的回滚（含 DB 快照恢复）不同。

## 不在快照内的站点配置（`.env` / `settings.py`，改动需重启）

| 配置 | 环境变量 | 说明 |
|---|---|---|
| 密钥 | `SECRET_KEY` | 生产（`DJANGO_DEBUG=0`）必须显式设置；本地 debug 有公开占位回退 |
| 调试 / 主机 | `DJANGO_DEBUG`、`ALLOWED_HOSTS` | DEBUG 控制 HSTS 与 Secure cookie 开关 |
| Turnstile secret | `TURNSTILE_SECRET_KEY` | 仅进程内使用，永不下发 |
| 邮件 | `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | 配了即切 163 SMTP（SSL 465），否则 dev 用 console 后端 |
| 前端地址 | `FRONTEND_URL` | 用于拼认证邮件 / 重置链接（默认 `http://localhost:3000`） |
| 媒体路径 | — | `MEDIA_ROOT`（公开）、`PRIVATE_MEDIA_ROOT`（身份证明，鉴权下载） |
| 自动更新凭据 | `UPDATE_GITHUB_TOKEN`、`UPDATE_GITHUB_REPO` | token 为密钥；repo 默认 `nhyzcms/club-management-website` |
| 数据库 / Redis / worker | `DB_ENGINE` 等 `DB_*`、`REDIS_URL`、`GUNICORN_WORKERS` | 缺省 SQLite + 单 worker；可选 PostgreSQL + Redis 多 worker（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)） |

## 相关实现位置

| 关注点 | 位置 |
|---|---|
| 快照读取与默认值 | `common/policy.py`（`get_policy` / `SitePolicy` / `invalidate_policy_cache` / `format_byte_cap`） |
| 单例模型与 admin 编辑 | `common/models.py`（`SiteSettings`）、`common/admin.py` |
| 公开视图 | `common/views.py`（`SitePolicyView`） |
| 维护拦截与旗标 | `common/middleware.py`、`common/maintenance.py`、`common/management/commands/maintenance.py` |
| 自动更新 | `common/updater.py` |
