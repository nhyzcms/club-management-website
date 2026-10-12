# 部署与运维指南

生产环境是 **Nginx + Gunicorn（ASGI / `UvicornWorker`）+ systemd**，Django 直接托管 React 构建产物。数据库缺省 SQLite 单文件，可切 PostgreSQL；ASGI worker 缺省 1，配置 Redis 频道层后可由 `GUNICORN_WORKERS` 提高（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)）。本文覆盖安装、更新、回滚、备份与排障。

> 相关：[ADR-0015](../adr/0015-channels-without-redis.md)（缺省单 worker · 内存通道层）、[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)（PostgreSQL / Redis / 多 worker）、[快速开始](../getting-started.md)（本地开发）、[配置参考](../configuration.md)（环境变量与站点策略逐项说明）

## 1. 运行架构

```
浏览器
  ↓  HTTP/1.1；有证书后可 HTTP/2（HTTP/3 可选）
Nginx
  ├── /static/ → Django staticfiles（collectstatic 产物）
  ├── /media/  → 用户上传文件
  └── 其余（含 /ws/messaging/、/ws/exam-board/）
        ↓  一律 HTTP/1.1 + Upgrade（unix socket）
      Gunicorn UvicornWorker × 1 → Django ASGI
        ├── config.asgi:application（HTTP + WebSocket）
        └── scripts/updater.py（同一 systemd cgroup 内的兄弟进程）
```

关键事实（全部可在仓库中核对）：

- `start.sh` 用 `exec` 启动 `gunicorn -k uvicorn.workers.UvicornWorker --workers "${GUNICORN_WORKERS:-1}" --bind unix:$DIR/run/gunicorn.sock config.asgi:application`，并以兄弟进程身份拉起 `scripts/updater.py`。
- **worker 缺省为 1**：`CHANNEL_LAYERS` 缺省 `InMemoryChannelLayer`，不能跨进程扇出（[ADR-0015](../adr/0015-channels-without-redis.md)）。配置 `REDIS_URL`（Redis 频道层，[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)）后可用 `GUNICORN_WORKERS` 提高；SQLite 怕多写者，生产多 worker 建议同时切 PostgreSQL。
- WebSocket 两条：`/ws/messaging/`（须登录，推私信 / 通知 / 当前评论区）与 `/ws/exam-board/`（匿名可连，教室看板课表与题目误刊广播，[ADR-0018](../adr/0018-exam-board-batch-and-public-ws.md)）。
- 前端 `frontend/dist/` 由 Django 的 `TEMPLATES["DIRS"]` 直接渲染，`STATICFILES_DIRS` 收集其静态资源；**没有独立的前端服务**。
- 更新守护进程与 Gunicorn 同生命周期：停 `club` 时 systemd 清整个 cgroup，因此没有单独的 `club-updater.service`（`scripts/install.sh` 会停用并移除历史遗留的该 unit）。
- 维护拦截是**文件旗标** `run/MAINTENANCE`，中间件只读文件、不读数据库——保证 `migrate` 期间不会死锁 SQLite。

### Nginx 两段协议

两段连接协议可以不同，但**不要**按路径拆成「`/ws/` 走一套、其余走另一套」两个 `location`。一个 `location /` 反代到 unix socket 即可。

| 段 | 协议 |
|---|---|
| 浏览器 → nginx | HTTP/1.1；有 TLS 后可在 `listen` 上开 HTTP/2；HTTP/3 可选 |
| nginx → Gunicorn | **一律 HTTP/1.1**（页面、API、WebSocket 的 `Upgrade` 都在这一段） |

Uvicorn 在 unix socket 上只说 HTTP/1.1。nginx 1.29.7 之前 `proxy_http_version` 默认是 HTTP/1.0，不写 `1.1` 则 WebSocket 握手失败；不要写 `proxy_http_version 2`。

`scripts/install.sh` 写入的站点文件（Debian 布局 `/etc/nginx/sites-available/<服务名>`，RHEL / 阿里云布局 `/etc/nginx/conf.d/<服务名>.conf`）内容如下（`$DIR` 为安装目录）：

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name club.example.com;
    client_max_body_size 20M;
    server_tokens off;

    # 静态文件缓存：哈希构建产物 → 1 年 immutable；其余与 /media/ → 7 天（详见「静态文件缓存」小节）
    location ~ "^/static/(.+\.[0-9a-f]{20}\..+)$" {
        alias /opt/club/staticfiles/$1;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
    }
    location /static/ {
        alias /opt/club/staticfiles/;
        expires 7d;
    }
    location /media/ {
        alias /opt/club/media/;
        expires 7d;
    }

    error_page 502 /maintenance.html;
    location = /maintenance.html {
        alias /opt/club/static/maintenance.html;
        default_type text/html;
        charset utf-8;
        internal;
    }

    location / {
        proxy_pass http://unix:/opt/club/run/gunicorn.sock;
        proxy_http_version 1.1;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        $connection_upgrade;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # 空闲 WebSocket 否则约 60s 被掐；前端会重连，但会抖
        proxy_read_timeout 7d;
        proxy_send_timeout 7d;
    }
}
```

已上 HTTPS 的机器：**更新器不会改 Nginx**。需要在 443 的 `server` 里补同一套反代头、`server_tokens off` 与 HSTS，改完 `nginx -t && systemctl reload nginx`：

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name club.example.com;
    ssl_certificate     /etc/letsencrypt/live/club.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/club.example.com/privkey.pem;
    client_max_body_size 20M;
    server_tokens off;
    add_header Strict-Transport-Security "max-age=31536000" always;
    # location /static/、/media/、error_page 与 location / 与 80 的块相同
}
```

Django 在 `DJANGO_DEBUG=0` 时也会对 HTTPS 响应发同一条 HSTS（`SECURE_HSTS_SECONDS = 31536000`，`config/settings.py`）；重复同值无害。不要开 `includeSubDomains` / `preload`，除非确认该域名下没有仍走 HTTP 的子域。

#### 静态文件缓存

`/static/`、`/media/` 由 `install.sh` 模板写入三层缓存策略：

- **哈希构建产物**（webpack `[contenthash]`，文件名含 20 位十六进制，如 `main.461273a96dc7c5b5be62.js`）→ `Cache-Control: public, max-age=31536000, immutable`。文件名与内容一一对应，长缓存安全。
- **其余 `/static/`**（`admin/`、`surveyjs/`、`live2d/` 等无哈希文件）→ `expires 7d`：换版后最长 7 天陈旧窗口，过期由浏览器带 `If-None-Match` / `If-Modified-Since` 发起协商（304）。
- **`/media/` 用户上传**（UUID / `user_<id>` 命名，URL 与内容一一对应）→ `expires 7d`。

注意：带 `add_header` 的 `location`（哈希产物块）会**覆盖 server 级 `add_header` 的继承**——在 443 使用且 server 级配了 HSTS / Alt-Svc 时，需在该块内重复声明这两个头，否则哈希产物的响应会缺失它们。

#### 启用 HTTP/3（可选，nginx 1.25+）

QUIC / HTTP/3 需要 nginx ≥ 1.25 且构建参数含 `--with-http_v3_module`（安装后 `nginx -V 2>&1 | grep http_v3` 现场核验；发行版自带的老版 nginx 通常没有）。要点：

- 同一 `server` 块保留 `listen 443 ssl;`，新增 `listen 443 quic reuseport;`（`reuseport` 全站只写一处），`ssl_protocols` 含 `TLSv1.3`。
- 下发 `Alt-Svc: h3=":443"`（部分版本会自动下发，重复同值无害）。
- **云安全组 / 防火墙放行 UDP 443**，否则客户端会静默回退 HTTP/2。
- 验证：浏览器 DevTools 的协议列，或 `curl --http3-only https://<域名>/`（本地 curl 需带 HTTP/3 支持）。

```nginx
server {
    listen 443 ssl;
    listen 443 quic reuseport;
    http2 on;                      # nginx 1.25+ 推荐的写法（替代 listen ... http2）
    server_name club.example.com;
    # …证书与其它指令同上（见上一节）
    add_header Alt-Svc 'h3=":443"; ma=86400' always;
}
```

## 2. 环境要求

| 组件 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Debian / Ubuntu / 阿里云 Linux / RHEL 系 | `install.sh` 自动识别 `apt` / `dnf` / `yum` |
| Python | 3.14 | `pyproject.toml` 声明 `requires-python = ">=3.14"`；`uv sync` 会自行准备解释器 |
| uv | 0.11+ | `install.sh` 在服务用户下自动安装（`astral.sh/uv/install.sh`） |
| Node.js | 22（仅就地构建前端时需要） | Release 包已含 `frontend/dist`，独立安装不需要 Node |
| 数据库 | 缺省 SQLite（`db.sqlite3`）；可选 PostgreSQL 17+ | PostgreSQL 由 `DB_ENGINE=postgresql` 启用（只监听 `127.0.0.1`）；留空即 v1 行为（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)） |
| 缓存 / 频道层 | 缺省无；可选 Redis 6+ | 配 `REDIS_URL` 同时供缓存与 Channels 跨进程扇出；多 worker 前置条件 |
| 其他 | nginx、curl、tar、gzip、git、sqlite3、编译链 | 由 `install.sh` 按包管理器安装；`--skip-deps` 可跳过 |
| 磁盘 | 预留 `backups/` 空间 | 发行包（默认保留 3 份）+ DB 快照（默认保留 5 份）+ media |

端口与网络：Gunicorn 只监听 unix socket（`run/gunicorn.sock`），对外仅 Nginx 的 80/443。生产不需要开放其他端口。

## 3. 安装

支持两条路径：**已有源码树**（clone 或解压过 Release），或**机器上还没有源码**（脚本自己拉最新 GitHub Release）。两条路径共用 `scripts/install.sh`。

### 3.1 独立安装（无需先 clone）

适合新机器。Release 资产里带 `install.sh`、`club-<sha>.tar.gz` 与 `.sha256`，包内已含 `frontend/dist`。

```bash
# 公开仓库；管道安装必须带 -y（否则 read 会吞掉脚本自身）。
# 私有仓库先 export GITHUB_TOKEN=...
curl -fsSL https://github.com/nhyzcms/club-management-website/releases/latest/download/install.sh | sudo bash -s -- -y
```

或下载后再跑（便于先看参数）：

```bash
curl -fsSL https://github.com/nhyzcms/club-management-website/releases/latest/download/install.sh -o install.sh
sudo APP_DIR=/opt/club APP_USER=club SERVER_NAME=club.example.com \
    FRONTEND_URL=http://club.example.com SUPERUSER_PASSWORD='...' bash install.sh -y
```

指定历史版本：

```bash
sudo bash install.sh --from-release club-<sha>
```

默认安装到 `/opt/club`，服务用户 `club`，systemd unit 名 `club`。

### 3.2 仓库内就地部署

在 clone 目录执行：

```bash
sudo ./scripts/install.sh
```

可用参数与环境变量（`scripts/install.sh` 实读）：

| 参数 / 变量 | 作用 |
|---|---|
| `--skip-deps` | 跳过系统包安装（自己先装好 nginx / 编译链等） |
| `-y` / `--yes` | 非交互；管道安装必带 |
| `--from-release [tag]` | 强制从 GitHub Release 拉包；可跟 tag / sha |
| `APP_DIR` | 安装目录（默认 `/opt/club`） |
| `APP_USER` | 服务用户（就地安装默认取目录属主；独立安装默认 `club`） |
| `SERVICE_NAME` | systemd / nginx 服务名（默认 `club`） |
| `SERVER_NAME` | nginx `server_name`（默认 `_`，即任意 / 按 IP） |
| `FRONTEND_URL` | 拼邮件链接用的站点来源（默认按 `SERVER_NAME` 或首张网卡 IP 推导） |
| `SUPERUSER_USERNAME` / `SUPERUSER_EMAIL` / `SUPERUSER_PASSWORD` | 首个超级用户；密码留空则随机生成并只打印一次 |

脚本逐步做的事：

1. 按包管理器安装系统依赖（`build-essential` / `gcc` / `nginx` / `sqlite3` / `curl` / `git` 等）。
2. 就地安装且缺 `frontend/dist` 时安装 Node.js 22 并构建前端；独立安装跳过（包内已有产物）。
3. 确定安装目录与服务用户（必要时 `useradd -r`）。
4. 以服务用户身份执行 `uv sync --frozen`（缺 uv 则先装）。
5. 生成 / 补全 `.env`：`SECRET_KEY`（空则 `secrets.token_urlsafe(48)`）、`FRONTEND_URL`、`DJANGO_DEBUG=0`、`ALLOWED_HOSTS`（由 `FRONTEND_URL` 主机名 + `SERVER_NAME` + `127.0.0.1,localhost` 去重拼接）；随后 `chmod 600` 并改属服务用户。已有非空值一律跳过。
6. 执行 `migrate` 与 `collectstatic --noinput`，写 `run/applied-release`（就地安装取 `git rev-parse HEAD`；独立安装取包名里的 SHA）。
7. 创建第一个超级用户（已存在超管则跳过；`createsuperuser --noinput`）。
8. 写 `/etc/systemd/system/club.service`（`Type=notify`、`ExecStart=$DIR/start.sh`、`ExecReload=/bin/kill -s HUP $MAINPID`、`Restart=on-failure`）。
9. 写 Nginx 站点（Debian 布局建软链并删 `default`；RHEL 布局把 `default.conf` 改名 `.disabled`），`nginx -t` 后 reload。
10. 写 `/etc/sudoers.d/club`：服务用户免密执行 `systemctl start|stop|restart|reload|is-active club`（更新器重载服务用）。
11. `systemctl daemon-reload && systemctl enable --now club`。
12. SELinux 处于 Enforcing / Permissive 时给 `staticfiles` / `static` / `media` / `run` 打标签并放行 `httpd_can_network_connect`；有 firewalld 则放行 `http`。

### 3.3 安装后的收尾

脚本结尾会打印访问地址与超管账号。建议继续：

```bash
# 1) 补可选凭据（邮件 / Turnstile / 更新 token），然后重启
sudo nano /opt/club/.env
sudo systemctl restart club

# 2) 登录 /admin/，把成员加入「社长」「信息组」组（没组 = 没权限）
# 3) /admin/ 的「站点策略」里调更新窗口与轮询间隔
```

## 4. 环境变量

全部通过 `.env` 管理（模板 `.env.example` 入库；`.env` 已 gitignore）。`start.sh` 在 `.env` 缺失时会从模板复制一份，随后 `set -a; . ./.env` 导出给 Gunicorn / Django。

| 变量 | 用途 | 生产 |
|---|---|---|
| `SECRET_KEY` | Django 签名密钥 | **必填**；`DJANGO_DEBUG=0` 且留空时进程拒绝启动（`ImproperlyConfigured`） |
| `DJANGO_DEBUG` | 调试开关 | 设 `0`；`install.sh` 会写 |
| `ALLOWED_HOSTS` | 允许的 Host，逗号分隔 | **必填**；`install.sh` 会写 |
| `FRONTEND_URL` | 邮件链接来源 | 建议填站点域名 |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | 163 邮箱账号与 **SMTP 授权码** | 按需；不配则邮件走 console 后端 |
| `NOTIFICATIONS_DELIVERY_ASYNC` | 通知外发投递模式 | 默认异步（进程内队列，失败自动退避重试）；`=0` 回退同步投递（见 [ADR-0024](../adr/0024-async-notification-delivery.md)） |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile | 按需；两项都空 = 关闭，只填一半也视为关闭 |
| `UPDATE_GITHUB_TOKEN` | 读 Release 用的 GitHub PAT | **必填**（自动更新依赖） |
| `UPDATE_GITHUB_REPO` | `owner/repo` | 默认 `nhyzcms/club-management-website` |
| `DB_ENGINE` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | 数据库切换与连接 | 留空 = SQLite；`DB_ENGINE=postgresql` 启用 PostgreSQL |
| `REDIS_URL` | 缓存 + 频道层 | 留空 = v1；配置后可用 `GUNICORN_WORKERS` >1 |
| `GUNICORN_WORKERS` | ASGI worker 数 | 默认 `1`；**须配 `REDIS_URL`** |
| `CLUB_UPDATER_PROXY` | 更新器出站代理（仅注入守护进程，加速下载） | 留空 = 不注入；如 `http://127.0.0.1:7891` |

逐项默认值、派生逻辑与相关测试见[配置参考](../configuration.md)。另有几个不在模板中、由代码读取的变量：`CLUB_SPAWN_UPDATER=0`（只起 web、不拉起更新守护进程，排障用）、`CLUB_UPDATER_SPAWNED`（由 `start.sh` 置 1）、`SERVICE_NAME`（更新器重载服务用，默认 `club`）。

## 5. 日常服务管理

```bash
sudo systemctl status club          # 状态
sudo systemctl restart club         # 重启（读 .env 变更）
sudo systemctl stop club            # 停止（连同更新守护进程）
sudo systemctl reload club          # SIGHUP，平滑重载 worker
sudo journalctl -u club -f          # 跟日志（web + 更新器同一条流）
sudo journalctl -u club -n 100 --no-pager
```

前台排障（Ctrl-C 停，不影响 systemd 下的实例）：

```bash
cd /opt/club && ./start.sh
```

维护拦截（写 `run/MAINTENANCE`，全站 503，含 `/admin/`）：

```bash
uv run python manage.py maintenance on --message "机房维护，预计 30 分钟"
uv run python manage.py maintenance status
uv run python manage.py maintenance off
```

更新进行中执行 `on` 会记下 `resume_ops`，更新结束后自动恢复运维拦截；`off` 不会中止进行中的更新。

身份有效期兜底（撤销过期管理员、停用超期未认证账号；登录 / 请求时的惰性执行只覆盖来访问的账号，建议用 cron / systemd timer 定期兜底），并同时发**到期前提醒**（身份还剩两个月 / 一个月，站内通知；台账保证只发一次，见[身份验证](../guides/verification.md#到期前提醒降权预警)）：

```bash
uv run python manage.py enforce_validity                 # 执行一次（含到期前提醒）
uv run python manage.py enforce_validity --dry-run       # 只统计，不改动（提醒也不落库）
uv run python manage.py enforce_validity --skip-notices  # 只做降权 / 停用，不发提醒
```

通知外发（邮件）默认**异步**投递（进程内队列 + 守护线程，失败自动退避重试、重启不丢，见 [ADR-0024](../adr/0024-async-notification-delivery.md)）——手动补投 / 排障入口：

```bash
uv run python manage.py flush_notifications              # 排空内存队列 + 补投到期的待投递行
uv run python manage.py flush_notifications --limit 500  # 限量（默认 200）
```

Nginx 侧：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 6. 升级流程

生产升级走 **GitHub Release + 更新守护进程**，不要在服务器上 `git pull` 再手工构建（独立安装的机器往往没有 git 历史，Release 包也不含 `.git`）。

### 6.1 自动更新

`start.sh` 拉起 `scripts/updater.py`，与 Gunicorn 同 cgroup、同生命周期。行为要点：

- **轮询**：按站点策略 `update_poll_interval_seconds`（默认 900 秒）查 GitHub Release，下载 `club-<sha>.tar.gz` + `.sha256` 到 `backups/releases/`，支持 HTTP Range 断点续传、校验失败重下、最多 8 次指数退避重试；未完成的 `.part` 绝不参与应用。首次启动还会预取当前 `run/applied-release` 对应包，作为回滚保险。
- **应用窗口**：`auto_update_enabled` 为真、当前处于 `[update_window_start_hour, update_window_end_hour)`（`update_timezone`，默认 `Asia/Shanghai` 01:00–03:00）、且距窗口结束还有 `update_apply_cutoff_minutes_before_end`（默认 30）分钟以上，才会开始应用。
- **应用步骤**：写维护旗标（`drain` 拦截访问）→ 备份数据库（SQLite `.backup` 或 PostgreSQL `pg_dump --clean`，写到 `backups/db-<时间戳>.sqlite3` / `.pg.sql`，按 `update_db_backup_keep` 裁剪）→ 解包到 `backups/staging-*` → 替换代码树（`.env`、`db.sqlite3*`、`media`、`private_media`、`run`、`backups`、`.venv`、`.git` 一律排除）→ `uv sync --frozen` → `migrate` → `collectstatic` → 重载服务并健康检查（`systemctl is-active`）。
- **成功后**：写 `run/applied-release`，按 `update_release_keep` 裁剪旧包，撤下维护页。
- **失败 / 窗口关闭**：自动回滚——恢复上一发行包代码树 + 应用前的 DB 快照 + 重载；若回滚后服务不健康，保留维护页。

维护页按 8 步显示进度（拦截访问 / 备份数据库 / 解包更新 / 替换文件 / 同步依赖 / 迁移数据库 / 收集静态文件 / 重载服务），回滚时显示「正在回滚到上一版本」。

### 6.2 手动立即升级

忽略窗口，立刻升到最新 Release（或指定包）：

```bash
cd /opt/club
set -a; . ./.env; set +a
.venv/bin/python scripts/updater.py --apply-now
```

`--apply-now` 的 `SHA` 参数可以是完整 hash、7 位以上前缀、`club-<sha>` 标签，或磁盘上已有的 `club-*.tar.gz` 路径；省略则下载并应用 GitHub latest：

```bash
.venv/bin/python scripts/updater.py --apply-now a03abc2
.venv/bin/python scripts/updater.py --apply-now club-<fullsha>
.venv/bin/python scripts/updater.py --apply-now backups/releases/club-<fullsha>.tar.gz
```

以服务用户身份执行（文件属主正确、`sudo systemctl` 免密生效）：

```bash
sudo -u club HOME=$(getent passwd club | cut -d: -f6) bash -lc \
  'cd /opt/club && set -a; . ./.env; set +a && .venv/bin/python scripts/updater.py --apply-now'
```

中断处理：`--apply-now` / `--rollback` 在终端里 Ctrl+C 不会立刻杀掉半套树——当前步骤结束后询问：

- 尚未替换文件：[a] 取消更新并撤下维护页（回车默认）/ [c] 继续；
- 已经替换文件：[r] 回滚到上一版本并恢复这次更新前的数据库备份（回车默认）/ [c] 继续 / [h] 保持维护页人工处理。

无 TTY（守护进程）时走同一套默认值，不提问。回滚进行中的 Ctrl+C 会被忽略直到回滚结束。

### 6.3 回滚

回滚到任意一个以往的 Release。**只换代码树，不还原数据库**（SQLite / PostgreSQL 同此），以免丢上线后的数据（这与「应用失败时的自动回滚」不同——那条路径会恢复 apply 前的 DB 快照）：

```bash
cd /opt/club
set -a; . ./.env; set +a
.venv/bin/python scripts/updater.py --rollback            # 本地最新非当前包，否则 GitHub 上当前版本的前一个 Release
.venv/bin/python scripts/updater.py --rollback abc1234    # 7 位以上前缀
.venv/bin/python scripts/updater.py --rollback club-<fullsha>
```

Django 迁移不会自动反向：回滚只换代码与静态文件，数据库保持当前内容。若必须手工处理，先确认 `backups/releases/club-<sha>.tar.gz` 还在。**不要**在生产树里 `git checkout`。

升级 / 回滚后检查：

```bash
sudo systemctl status club
sudo journalctl -u club -n 50 --no-pager
cat /opt/club/run/applied-release
```

### 6.4 发布侧（仓库维护者）

`.github/workflows/ci.yml`：push 到 `main` 或任意 PR 触发 `backend`（`uv sync --frozen` + `manage.py test`）、`frontend`（Node 22 + `npm ci && npm run build` + 断言 SurveyJS 产物）、`frontend-test`（Vitest 单元 / 组件测试）与 `e2e`（Playwright 浏览器测试，复用 `frontend` 构建产物、自动起独立库与服务）四个 job；仅 push 到 `main` 且前四个通过时跑 `release` job——`bash scripts/pack-release.sh` 打包成 `club-<sha>.tar.gz` + `.sha256`，连同 `install.sh` 一起创建 GitHub Release（标签 `club-<sha>`，附上一个 Release 以来的 changelog）。`pack-release.sh` 只收 Django 应用、`config/`、`manage.py`、`pyproject.toml`、`uv.lock`、`scripts/`、`start.sh`、`.env.example`、`static/maintenance.html` 与 `frontend/dist/`。

## 7. 备份与恢复

### 7.1 数据面

| 内容 | 位置 | 说明 |
|---|---|---|
| 数据库（SQLite） | `<安装目录>/db.sqlite3` | 缺省部署的全部业务数据 |
| 数据库（PostgreSQL） | 本机 `club` 库（与站点同机） | `DB_ENGINE=postgresql` 时的全部业务数据 |
| 公开媒体 | `<安装目录>/media/` | 头像、新闻封面、活动图片、教程、附件、考试误刊等 |
| 私有媒体 | `<安装目录>/private_media/` | 身份证明（`IdentityProof`），**不在** `MEDIA_ROOT` 内，由鉴权视图服务 |
| 发行包 | `<安装目录>/backups/releases/` | 更新器缓存，也是回滚依据 |
| DB 快照 | `<安装目录>/backups/db-*.sqlite3`（或 `db-*.pg.sql`） | 更新器每次应用前自动生成（按引擎分派） |

更新器**不会**碰 `media` / `private_media` / `backups`（在同步排除清单里），因此这两处需要自行备份。

### 7.2 手动备份

SQLite 用 `.backup` 而不是 `cp`（运行中的库可能有未落盘事务）：

```bash
cd /opt/club
sqlite3 db.sqlite3 ".backup '/opt/club/backups/db-manual-$(date +%Y%m%d-%H%M%S).sqlite3'"
tar -czf backups/media-$(date +%Y%m%d).tar.gz media private_media
```

PostgreSQL 用 `pg_dump`（普通 SQL 格式，可直接 `psql -f` 还原）：

```bash
cd /opt/club
PGPASSWORD='<DB_PASSWORD>' pg_dump -h 127.0.0.1 -U club --clean --if-exists --no-owner --no-acl \
  -f "backups/db-manual-$(date +%Y%m%d-%H%M%S).pg.sql" club
tar -czf backups/media-$(date +%Y%m%d).tar.gz media private_media
```

建议保留最近 7–30 天版本，并同步到对象存储或 NAS。快照裁剪由站点策略 `update_db_backup_keep`（默认 5）控制，只作用于更新器自己生成的 `db-*.sqlite3`。

### 7.3 恢复

**数据库（SQLite）**：

```bash
sudo systemctl stop club
cd /opt/club
rm -f db.sqlite3-journal db.sqlite3-wal db.sqlite3-shm
cp backups/db-<时间戳>.sqlite3 db.sqlite3
chown club:club db.sqlite3
sudo systemctl start club
```

**数据库（PostgreSQL）**：

```bash
sudo systemctl stop club
cd /opt/club
PGPASSWORD='<DB_PASSWORD>' psql -h 127.0.0.1 -U club -v ON_ERROR_STOP=1 \
  -f backups/db-<时间戳>.pg.sql club
sudo systemctl start club
```

**媒体**：解包归档到安装目录对应位置，属主保持服务用户。

**代码**：优先用 `--rollback <sha>`（见 6.3），而不是手工解包——它会一并跑 `uv sync` / `collectstatic` 与重载。

恢复后核对 `sudo systemctl status club` 与关键页面（首页、`/admin/`、登录后 `/ws/messaging/` 握手）。

## 8. 常见故障与排查

### 8.1 访问 502 Bad Gateway

常见原因：Gunicorn 未启动 / 崩溃；`run/gunicorn.sock` 不存在或权限不对；SELinux 未打标签（阿里云 / RHEL 常见）。

```bash
sudo systemctl status club
sudo journalctl -u club -n 100 --no-pager
ls -l /opt/club/run/
sudo journalctl -u nginx -n 50 --no-pager
```

Nginx 的 `error_page 502` 会指向 `static/maintenance.html`，因此 502 时浏览器看到的可能是维护页而非默认错误页——先看日志判断根因。SELinux 机器确认 `staticfiles` / `media` / `run` 已打标签（`install.sh` 的 `selinux_labels`），必要时手工 `chcon -R -t httpd_sys_content_t` / `httpd_var_run_t`。

### 8.2 登录失败 / 403 / 429

- **403 `registration_closed` / `verification_closed`**：站点策略关闭了对应开关（`/admin/` → 站点策略）。
- **429 `login_throttled`**：登录失败次数超限（按 IP 与按用户名 / 邮箱双维度，额度在站点策略），响应带 `Retry-After`。
- **409 `login_protection`**：账号已有未满 10 分钟的当前会话且本次非同一会话再认证。
- **401 `session_superseded`**：同账号在别处登录，当前会话被挤下线（浏览器导航给 HTML 下线页，API 给 JSON）。
- **CSRF 失效**：检查 `Cookie` 是否带 `csrftoken` / `sessionid`；前端启动会显式 `GET /auth/csrf/`。若站点走 HTTPS，确认 Nginx 传了 `X-Forwarded-Proto`（`Secure` Cookie 依赖它）。
- **Host 头被拒**：`ALLOWED_HOSTS` 未包含真实域名。

### 8.3 静态文件 / 图片 404

```bash
cd /opt/club
set -a; . ./.env; set +a
uv run python manage.py collectstatic --noinput
```

再检查 `STATIC_ROOT`（`staticfiles/`）、`MEDIA_ROOT`（`media/`）与 Nginx 的 `location /static/`、`location /media/` 别名是否与安装目录一致。前端产物缺失时首页模板渲染会失败——确认 `frontend/dist/index.html` 存在。

### 8.4 `database is locked`

SQLite 在并发写入时的典型问题：

- SQLite 部署的契约是 **`--workers 1`**；要加 worker 先上 Redis 频道层（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)），并建议同时切 PostgreSQL（SQLite 多写者）。
- 更新流程里 `migrate` 与 web 请求可能短暂并存，维护页正是为此先把访问拦下来（`drain` 步骤）——不要绕过维护旗标手工 `migrate`。
- 避免大量热点写操作同时发生；必要时错峰批量操作。

### 8.5 WebSocket 连不上 / 约一分钟断一次

页面功能不受影响（评论、私信、通知走 HTTP，只是不实时推）：

- 站点配置缺 `proxy_http_version 1.1` 或 `Upgrade` / `Connection` 头（**更新器不会改 Nginx**）。
- 只改了 80 的 `server`，443 块没有同一套反代头。
- `start.sh` 还是旧的 WSGI / 多 worker 写法：须为 `UvicornWorker`、`--workers 1`、`config.asgi:application`。
- 约 60 秒断一次：补 `proxy_read_timeout 7d; proxy_send_timeout 7d;`。
- 检查 `CLUB_SPAWN_UPDATER` 等环境是否被误设、以及 `AllowedHostsOriginValidator` 是否因 `ALLOWED_HOSTS` 不含域名而拒绝握手。

### 8.6 自动更新不生效

- `UPDATE_GITHUB_TOKEN` 为空 → 守护进程日志会打 `UPDATE_GITHUB_TOKEN empty; skip download`。
- 站点策略 `auto_update_enabled` 关闭 → 跳过下载与应用。
- 不在窗口内或距窗口结束不足截止分钟数 → 只下载不应用（`--apply-now` 可绕过）。
- token 权限不足 / 仓库名不对 → 日志出现 `GitHub HTTP 401/403/404`；`UPDATE_GITHUB_REPO` 默认 `nhyzcms/club-management-website`。
- 想确认当前版本：`cat run/applied-release`；想看已下载的包：`ls -l backups/releases/`。
- 下载龟速 / 长期停在 `*.part`（直连 GitHub 慢）：给更新器单独配出站代理 `CLUB_UPDATER_PROXY`（见第 4 节），只影响更新器，不碰业务出站。

### 8.7 站点一直 503（维护页不撤）

```bash
cd /opt/club
set -a; . ./.env; set +a
uv run python manage.py maintenance status
```

`reason=update` 说明有更新 / 回滚卡住：看 `sudo journalctl -u club -n 200 --no-pager`，确认后可用 `--apply-now` 或 `--rollback` 收尾；必要时 `maintenance off` 强制撤下（注意：若更新仍在进行，`off` 只取消「结束后的运维拦截」，不中止更新）。

## 9. 监控与巡检

```bash
sudo journalctl -u club -f                 # web + 更新器日志（同一流）
sudo tail -f /var/log/nginx/error.log      # Nginx 错误
```

建议关注：服务活跃状态（`systemctl is-active club`）、`run/applied-release` 是否与预期版本一致、`backups/` 占用与快照新鲜度、登录失败与限流命中、磁盘余量、`/admin/` 操作记录。

## 10. 发布前 / 定期检查清单

发布前：

- [ ] `.env` 完整（`SECRET_KEY`、`ALLOWED_HOSTS`、`FRONTEND_URL` 非空；`DJANGO_DEBUG=0`）
- [ ] `ALLOWED_HOSTS` 含真实域名（含即将启用的新域名）
- [ ] Nginx 上游为 HTTP/1.1 + `Upgrade` / `Connection`；有 TLS 的 443 块同样具备
- [ ] `systemctl is-active club` 正常，`journalctl` 无异常
- [ ] 前端产物存在（`frontend/dist/index.html`）且 `collectstatic` 已跑
- [ ] 关键页面可开；登录后 `/ws/messaging/` 能握手；教室看板 `/ws/exam-board/` 能连

定期（建议每周）：

- [ ] 手工备份 `db.sqlite3` 与 `media` / `private_media`，并验证归档可解
- [ ] 检查 `backups/` 磁盘占用与 `update_release_keep` / `update_db_backup_keep` 设置
- [ ] 复核 `/admin/` 后台账号与组成员（离职 / 换届后及时回收）
- [ ] 查看站点策略是否仍符合当前运营需要（注册开关、限流额度、更新窗口）
