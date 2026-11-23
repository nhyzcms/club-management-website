# 公共 API（站点策略与站点级行为）

`common` app 提供的站点级公共能力：运行时策略的**公开子集**（`GET /site-policy/`）、运行版本与发行说明（`GET /version/`、`GET /changelog/`）、维护模式 503 拦截、`media/file/` 固定目录的公开服务，以及旋钮的 admin 编辑路径。`common` 自身没有 `urls.py`——这几个路径均由 `config/urls.py` 直接挂载。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0010](../adr/0010-runtime-site-policy.md)

## 模块约定

- **挂载位置**：`GET /site-policy/`（`SitePolicyView`）、`GET /version/`（`VersionView`）、`GET /changelog/`（`ChangelogView`），均无 app 前缀；`GET /file/{path}`（`re_path` + `django.views.static.serve`，`document_root = BASE_DIR/media/file`）。
- **策略快照（`common/policy.py`）**：运营旋钮住四张单例领域表（`AuthPolicy` / `RateLimitPolicy` / `UploadPolicy` / `ContentPolicy`，各 `pk` 恒 1，[ADR-0046](../adr/0046-site-settings-split.md)），调用方一律经 `get_policy()` 读，**不查模型**；快照按缓存键 `common.site_policy` 缓存（`timeout=None`，任一策略表 `save()` 时失效），四张表无行 / DB 不可用时回退到代码内默认值（与字段默认值一致，行为中立）。加旋钮 = 对应领域表的新字段 + 迁移 + 快照字段，不做通用 KV 袋。`UpdaterPolicy` 已随旧更新器删除（2026-11-21，迁移 `common/0023`）。
- **版本与发行说明（`common/version.py` / `common/changelog.py`）**：`build_info.json` / `changelog.json` 由 CI 在 `docker build` 前生成、随镜像分发（两者都不进仓库）；本地开发没有构建产物时，版本回落到已安装包元数据（`source="pyproject"`），发行说明回落到仓库里的 `CHANGELOG.md`。两个端点都 `AllowAny`、`Cache-Control: no-store`。
- **密钥与基础设施**（`SECRET_KEY`、SMTP、Turnstile secret、`FRONTEND_URL`、MEDIA 路径）仍在 `config/settings.py` + `.env`，改完需重启；**secret 永不下发**。
- **认证**：`/site-policy/`、`/version/`、`/changelog/` 均为 `AllowAny` 且 `authentication_classes = []`——匿名 GET，不碰 session / CSRF；`/file/{path}` 亦无鉴权。
- **写入路径**：旋钮只走 Django admin（`is_staff` + 对应领域表的 `change_*` 权限，四张单例、禁增删、changelist 直接跳表单）；无产品侧写接口。维护旗标走 `manage.py maintenance on|off`。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | `/site-policy/` | 公开 | — | 站点策略公开子集（allowlist）+ Turnstile 公开字段 |
| GET | `/version/` | 公开 | — | 运行版本快照（镜像内 `build_info.json`；本地回落到源码版本） |
| GET | `/changelog/` | 公开 | — | 当前版本的发行说明（前端更新弹窗数据源） |
| GET | `/file/{path}` | 公开 | — | `media/file/` 目录静态服务 |

## 端点详情

### 站点策略快照

`GET /site-policy/`

**认证**：公开（`AllowAny`，且显式关闭认证类）；**权限**：—。SPA 启动时拉取一次；前端在不可达时回退到内置默认值。

**响应 `200 OK`**（示例为默认值）

```json
{
  "verification_enabled": true,
  "verification_valid_days": 365,
  "admin_valid_days": 730,
  "registration_verify_days": 60,
  "registration_enabled": true,
  "comments_enabled": true,
  "comment_max_depth": 8,
  "dms_enabled": true,
  "sync_upload_max_bytes": 52428800,
  "turnstile_enabled": false,
  "turnstile_site_key": ""
}
```

> **这是一个显式 allowlist，不是全量快照**（审计 #274）。`common/views.py: PUBLIC_POLICY_FIELDS` 是唯一真源，`common/tests/test_public_policy.py` 冻结了字段集合——新增公开字段要三处同改。运维参数（`tus` 上限、各条 per-IP 限流阈值、内容审核开关）**不再匿名可读**，管理员在 Django 后台「认证策略 / 频控策略 / 上传策略 / 内容策略」里查看。

`turnstile_enabled` / `turnstile_site_key` 来自 `.env`（`TURNSTILE_SITE_KEY` 与 `TURNSTILE_SECRET_KEY` **都非空**才启用；只配一半视为关闭），叠加在快照之上返回，**不在**任何策略表内。未启用时 sitekey 为空串。

### 公开字段（allowlist）

只列 `/site-policy/` 会下发的字段。**其余运维 / 频控字段不再公开**，在 Django 后台「认证策略 / 频控策略 / 上传策略 / 内容策略」里查看与编辑（完整清单见 `docs/configuration.md`）。

| 字段 | 类型 | 默认 | 含义 / 消费方 |
|---|---|---|---|
| verification_enabled | bool | `true` | 认证通道总开关；关闭后不可新开 / 完成任何通道。消费方：`accounts` |
| verification_valid_days | int | `365` | 认证有效期（天）；到期后回落未认证，需重新认证。消费方：`accounts` |
| admin_valid_days | int | `730` | 管理员身份有效期（天）；到期撤销 `is_staff`，超管不受限 |
| registration_verify_days | int | `60` | 注册后认证宽限（天）；超期未认证自动停用 |
| registration_enabled | bool | `true` | 自助注册开关；关闭后注册返回 403 |
| comments_enabled | bool | `true` | 评论区开关；关闭后前端不显示评论区且无法发新评论，已有评论保留 |
| comment_max_depth | int | `8` | 评论最大嵌套深度（1–32；超深拒绝，不改挂） |
| dms_enabled | bool | `true` | 私信开关；关闭后不显示入口且无法发起 / 发送，已有会话保留 |
| sync_upload_max_bytes | int | `52428800`（50MB） | 同步上传单文件上限；前端据此选同步 / tus 通路 |
| turnstile_enabled | bool | `false` | Turnstile 是否启用；前端据此挂载挂件 |
| turnstile_site_key | string | `""` | 公开 sitekey（未启用时为空串；secret 永不下发） |

> 前端（`frontend/src/api/sitePolicy.ts`）内置同名默认值，`/site-policy/` 不可达时回退；`turnstile_enabled` / `turnstile_site_key` 用于挂载挂件并随请求带 `turnstile_token`。

### 调用示例

```bash
curl http://localhost:8000/site-policy/
curl -I http://localhost:8000/file/ClassIsland快速使用指南.pdf
```

`/site-policy/` 无缓存头、无 ETag；前端只在应用启动时拉一次，运行期以本地快照为准（旋钮改动后需刷新页面或等待下次启动）。服务端快照缓存走 Django cache 后端（缺省 `locmem` 进程内、不跨进程共享；配 `REDIS_URL` 后为 Redis、跨进程共享——[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)）——缺省后端下多 worker 时 admin 改旋钮只在当前进程即时生效，其余 worker 待缓存失效 / 重启后一致。

### 版本快照

`GET /version/`

**认证**：公开（`AllowAny`，且显式关闭认证类）；**权限**：—。缓存头为 `Cache-Control: no-store`——版本随部署变化，缓存住会让「部署到底生效没」看起来像没生效。

**响应 `200 OK`**（镜像内由 `build_info.json` 提供；字段固定，调用方不必判空）

```json
{
  "version": "1.1.0",
  "base_version": "1.1.0",
  "channel": "release",
  "tag": "v1.1.0",
  "commit": "3e698c64a5a61a463b3cb6624f2cf02966570c3b",
  "commit_short": "3e698c6",
  "commits_since_tag": 0,
  "built_at": "2026-11-21T05:25:00Z",
  "built_by": "allenjin-login",
  "source": "build_info.json"
}
```

`channel` 只有两个值：`release`（tag 构建，或提交本身改了 `pyproject.toml` 的 `version`）与 `dev`（其余分支构建，版本形如 `1.1.0-dev.3.g3e698c6`）。本地源码运行时 `source` 为 `pyproject`，版本取自已安装包元数据；`/version/` 与容器内 `python manage.py version [--json]` 同源。

### 发行说明

`GET /changelog/`

**认证**：公开；**权限**：—。数据源是镜像里的 `changelog.json`（CI 由 `CHANGELOG.md` 生成），本地开发回落到直接解析 `CHANGELOG.md`。

**响应 `200 OK`**

```json
{
  "version": "1.1.0",
  "released": "2026-11-21",
  "summary": "页面底部现在能看到版本号，发版后会告诉你这次改了什么。",
  "sections": [
    { "title": "新增", "items": ["页脚常驻版本号", "更新说明弹窗"] }
  ]
}
```

没有对应版本小节时返回空壳 `{"version": null, "released": null, "summary": null, "sections": []}`（不是 404 / 204，前端只需判断 `sections` 是否为空）。`summary` 取自该版本小节开头的引用块——自动生成的是 commit 原文，只有人写的这一句是「和你有什么关系」。前端按**发行说明版本**判弹窗（不看 `/version/` 的 `channel`）：本地记录的上次版本与这里的 `version` 不同、且 `sections` 非空才弹；首次访问只记录不弹，同一版的多个 dev 构建之间不会重复弹。`changelog.json` 只在发版时变，而生产通常跑 tag 之后的 dev 构建——按 `channel=release` 判会让弹窗在线上永不出现（2026-11-22 修复）。`ci` / `test` / `chore` / `build` 类改动不进给社员的这份。

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
- 旗标文件即事实源（JSON，含 `reason` / `message` / `step` / `step_index` / `step_total` / `sha` / `resume_ops` / `ops_message`），中间件只读文件、不读策略表——避免 migrate 期间 SQLite 死锁。
- 更新时页面按 8 步展示进度（`drain` 拦截访问 → `backup` 备份数据库 → `unpack` 解包 → `sync` 替换文件 → `deps` 同步依赖 → `migrate` 迁移 → `collectstatic` 收集静态 → `reload` 重载服务；回滚另显示「正在回滚到上一版本」，进度百分比按 `step_index / step_total` 计算）。**这套进度页只属于旧更新器**；容器部署的 `deploy.sh` 不写维护旗标，切换时的不可用窗口仅几秒。
- 运维入口：`manage.py maintenance on|off|status`。`on` 可带 `--message`（显示在维护页）；更新进行中执行 `on` 会记下 `resume_ops`，更新结束后自动恢复运维拦截；`off` 不会中止进行中的更新（只取消「结束后的运维拦截」）。
- 影响面：维护页对**全站**（含 `/admin/`）生效，API 客户端同样收到 503 HTML（非 JSON）。

### 升级与发布（容器 CD）

生产升级不再由应用进程完成。`common/updater.py` / `scripts/updater.py` 与 `UpdaterPolicy` 表已于 2026-11-21 彻底删除（迁移 `common/0023`），应用内没有任何自动更新路径。

- **构建**：`image.yml` 在 push `main` / `develop` 或手动 dispatch 时构建镜像、跑冒烟（布局守卫 / `migrate` / `/site-policy/` 返回 JSON / `/changelog/` 内容一致 / SPA 入口含 `id="root"`），推 `ghcr.io/nhyzcms/club-management-website:sha-<sha>` 与 `:latest`（手动 dispatch 也推，供发布收尾补镜像）；`release.yml` 另给镜像补 `vX.Y.Z` tag。
- **版本发布**：`release.yml` 在 `main` 上版本变化时打 tag、建 Release、滚动 Milestone；`ci.yml` 的 `release` job 在该提交带 `v*` tag 时把 `club-<sha>.tar.gz` + `.sha256` 挂到对应 Release（每个版本一份，供裸机 / 离线安装）。合并后若一条 check-run 都没有，用 `gh workflow run release.yml --ref main -f finish=1` 补收尾、再 `gh workflow run image.yml --ref main` 补镜像。
- **版本可见性**：判断「部署到底生效没」看 `/version/` 的 `base_version` 是否等于刚发布的 `vX.Y.Z`（`commits_since_tag` = 发布之后又进了几个提交）。`channel=release` 只表示这次构建的正是 tag 或改版本号的那次提交；发布之后 `main` 上还有 hotfix / 回流提交，所以**线上常见 `channel=dev`**，不能拿它当「还没切」的判据。
- **登记**：`deploy.yml` 只在 `main` 的 Image 成功后 SSH 执行 `deploy.sh stage`——只拉镜像并写 `run/pending-release`，不切换。
- **切换**：服务器上的 `club-deploy.timer` 每 5 分钟 tick，落窗口（默认 `[01:00, 03:00)` Asia/Shanghai，由 `.env` 的 `CLUB_DEPLOY_WINDOW_START/END` / `CLUB_DEPLOY_TZ` 控制）时 `apply`：`pg_dump`（直连 5432，不走 pgbouncer 6432）→ `migrate` → `collectstatic` → 重建容器 → 健康检查（失败自动回滚到上一 tag）。
- **手动入口**：`deploy.sh status|now <tag>|stage <tag>|rollback|tick`；`rollback` 只换镜像、不还原数据库（详见[部署指南](../operations/deployment.md) §6）。

## 不在快照内的站点配置（`.env` / `settings.py`，改动需重启）

| 配置 | 环境变量 | 说明 |
|---|---|---|
| 密钥 | `SECRET_KEY` | 生产（`DJANGO_DEBUG=0`）必须显式设置；本地 debug 有公开占位回退 |
| 调试 / 主机 | `DJANGO_DEBUG`、`ALLOWED_HOSTS` | DEBUG 控制 HSTS 与 Secure cookie 开关 |
| Turnstile secret | `TURNSTILE_SECRET_KEY` | 仅进程内使用，永不下发 |
| 邮件 | `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | 配了即切 163 SMTP（SSL 465），否则 dev 用 console 后端 |
| 前端地址 | `FRONTEND_URL` | 用于拼认证邮件 / 重置链接（默认 `http://localhost:3000`） |
| 媒体路径 | — | `MEDIA_ROOT`（公开）、`PRIVATE_MEDIA_ROOT`（身份证明，鉴权下载） |
| 旧更新器凭据 | `UPDATE_GITHUB_TOKEN`、`UPDATE_GITHUB_REPO` | 仅 `scripts/install.sh` 的独立安装（拉 Release）沿用；容器部署不读取 |
| 数据库 / Redis / worker | `DB_ENGINE` 等 `DB_*`、`REDIS_URL`、`GUNICORN_WORKERS` | 缺省 SQLite + 单 worker；可选 PostgreSQL + Redis 多 worker（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)） |

## 相关实现位置

| 关注点 | 位置 |
|---|---|
| 快照读取与默认值 | `common/policy.py`（`get_policy` / `SitePolicy` / `invalidate_policy_cache` / `format_byte_cap`） |
| 四张单例策略表与 admin 编辑 | `common/models.py`（`AuthPolicy` / `RateLimitPolicy` / `UploadPolicy` / `ContentPolicy`）、`common/admin.py` |
| 公开视图 | `common/views.py`（`SitePolicyView`） |
| 维护拦截与旗标 | `common/middleware.py`、`common/maintenance.py`、`common/management/commands/maintenance.py` |
| 版本快照 | `common/version.py`、`common/management/commands/version.py`、`scripts/gen-build-info.sh` |
| 发行说明 | `common/changelog.py` / `common/changelog_parse.py`、`scripts/gen_changelog.py` |
| 升级与发布 | `.github/workflows/ci.yml`（`release` job）/ `image.yml` / `deploy.yml` / `release.yml`、`scripts/deploy.sh` |
