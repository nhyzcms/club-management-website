# 部署与运维指南

生产环境是 **Nginx + Docker 容器**（容器内 Gunicorn ASGI / `UvicornWorker`），Django 直接托管 React 构建产物。数据库缺省 SQLite 单文件，可切 PostgreSQL；ASGI worker 缺省 1，配置 Redis 频道层后可由 `GUNICORN_WORKERS` 提高（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)）。本文覆盖安装、更新、回滚、备份与排障。

> 相关：[ADR-0015](../adr/0015-channels-without-redis.md)（缺省单 worker · 内存通道层）、[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)（PostgreSQL / Redis / 多 worker）、[统一数据根](data-root.md)（数据目录结构与换根）、[快速开始](../getting-started.md)（本地开发）、[配置参考](../configuration.md)（环境变量与站点策略逐项说明）

## 1. 运行架构

```
浏览器
  ↓  HTTP/1.1；有证书后可 HTTP/2（HTTP/3 可选）
Nginx
  ├── /static/ → Django staticfiles（collectstatic 产物）
  ├── /media/  → 用户上传文件
  └── 其余（含 /ws/messaging/、/ws/exam-board/）
        ↓  一律 HTTP/1.1 + Upgrade（unix socket）
      Docker 容器 club-app（network_mode: host）
        └── Gunicorn UvicornWorker × N → Django ASGI
              └── config.asgi:application（HTTP + WebSocket）
```

升级不再由容器内的守护进程完成：CI 构建新镜像，窗口内重建容器（见 §6）。

关键事实（全部可在仓库中核对）：

- 容器入口是 `docker/entrypoint.sh`（子命令 `web` / `web-tcp` / `migrate` / `collectstatic` / `check` / `shell`），最终 `exec` 的是 `start.sh` → `gunicorn -k uvicorn.workers.UvicornWorker --workers "${GUNICORN_WORKERS:-1}" --bind unix:/app/run/gunicorn.sock config.asgi:application`。容器以 `network_mode: host` 运行，`.env` 里的 `127.0.0.1:6432` / `127.0.0.1:6379` 不需要改。
- **worker 缺省为 1**：`CHANNEL_LAYERS` 缺省 `InMemoryChannelLayer`，不能跨进程扇出（[ADR-0015](../adr/0015-channels-without-redis.md)）。配置 `REDIS_URL`（Redis 频道层，[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)）后可用 `GUNICORN_WORKERS` 提高；SQLite 怕多写者，生产多 worker 建议同时切 PostgreSQL。
- WebSocket 两条：`/ws/messaging/`（须登录，推私信 / 通知 / 当前评论区）与 `/ws/exam-board/`（匿名可连，教室看板课表与题目误刊广播，[ADR-0018](../adr/0018-exam-board-batch-and-public-ws.md)）。
- 前端 `frontend/dist/` 由 Django 的 `TEMPLATES["DIRS"]` 直接渲染，`STATICFILES_DIRS` 收集其静态资源；**没有独立的前端服务**。
- **没有更新守护进程**。旧的 `scripts/updater.py` / `common/updater.py` 与 `UpdaterPolicy` 表已于 2026-11-21 删除，生产升级只有容器一条路径：「CI 推镜像 → 窗口内重建容器」。容器带 `restart: unless-stopped` 且 Docker 已 `enable`，重启机器后站点自动恢复。
- 明信片照片清理由独立的 **`club-postcard-gc.timer`**（hourly，`Persistent=true`）驱动 `manage.py postcard_photo_gc`；它与 web 服务生命周期解耦，安装脚本自动创建并启用。
- 维护拦截是**文件旗标** `run/MAINTENANCE`，中间件只读文件、不读数据库——保证 `migrate` 期间不会死锁 SQLite。

### Nginx 两段协议

两段连接协议可以不同，但**不要**按路径拆成「`/ws/` 走一套、其余走另一套」两个 `location`。一个 `location /` 反代到 unix socket 即可。

| 段 | 协议 |
|---|---|
| 浏览器 → nginx | HTTP/1.1；有 TLS 后可在 `listen` 上开 HTTP/2；HTTP/3 可选 |
| nginx → Gunicorn | **一律 HTTP/1.1**（页面、API、WebSocket 的 `Upgrade` 都在这一段） |

Uvicorn 在 unix socket 上只说 HTTP/1.1。nginx 1.29.7 之前 `proxy_http_version` 默认是 HTTP/1.0，不写 `1.1` 则 WebSocket 握手失败；不要写 `proxy_http_version 2`。

旧裸机安装脚本 `scripts/install.sh` 写入的站点文件（容器化部署沿用现有 nginx 配置，安装脚本**不会**重写它）内容如下（`$DIR` 为安装目录）：

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name club.example.com;
    client_max_body_size 600M;   # ≥ 大文件（图 / 视频）500MB 上限 + 余量；同步上传上限由站点策略另控
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
        # 上传文件由 nginx 直出、不经 Django，安全头必须在这里单独声明（审计 #275）
        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options SAMEORIGIN always;
        add_header Content-Security-Policy "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox" always;
    }

    # 413 走站点自己的中文 JSON（审计 #272）：默认是 nginx 英文 HTML 页
    error_page 413 = @payload_too_large;
    location @payload_too_large {
        default_type application/json;
        return 413 '{"error":"上传文件过大，已被服务器拒绝。","reason":"payload_too_large"}';
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

> 采用统一数据根（`data/` 布局）的机器：`/media/` 与 `/app-update/` 的 `alias` 以 `<安装目录>/data/` 前缀为准——初始化与换根操作见[统一数据根](data-root.md)。

已上 HTTPS 的机器：**容器部署不会改 Nginx**。需要在 443 的 `server` 里补同一套反代头、`server_tokens off` 与 HSTS，改完 `nginx -t && systemctl reload nginx`：

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name club.example.com;
    ssl_certificate     /etc/letsencrypt/live/club.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/club.example.com/privkey.pem;
    client_max_body_size 600M;   # ≥ 大文件（图 / 视频）500MB 上限 + 余量；同步上传上限由站点策略另控
    server_tokens off;
    add_header Strict-Transport-Security "max-age=31536000" always;
    # location /static/、/media/、@payload_too_large、error_page 与 location / 与 80 的块相同
    # 注意：/media/ 与 /static/ 哈希块自带 add_header，会覆盖 server 级继承——
    # 上面的 HSTS 必须在这两个 location 内再写一遍，否则那批响应会丢 HSTS。
}
```

Django 在 `DJANGO_DEBUG=0` 时也会对 HTTPS 响应发同一条 HSTS（`SECURE_HSTS_SECONDS = 31536000`，`config/settings.py`）；重复同值无害。不要开 `includeSubDomains` / `preload`，除非确认该域名下没有仍走 HTTP 的子域。

#### 上传上限的唯一真源

`client_max_body_size` 有三处会写值：站点策略表、`scripts/install.sh` 模板、线上 `/etc/nginx/conf.d/*.conf`。**只有前两处跟着代码走，第三处不跟**——于是真实发生过「仓库 600M、测试断言不许是 20M、线上仍是 20M」的漂移：20–50MB 的附件在 nginx 层就被 413，Django 根本收不到（审计 #272）。

约定：

- **站点策略是上限的唯一来源**（`sync_upload_max_bytes` 与 `tus_media_max_bytes` 取大者），nginx 只做 **≥ 策略** 的兜底。
- 部署后跑一次自检，漂移就以非零码退出，可直接挂进巡检：

```bash
sudo -u club /opt/club/.venv/bin/python /opt/club/manage.py nginx_doctor
# 或只看某个配置文件：
python manage.py nginx_doctor --nginx-conf /etc/nginx/conf.d/club.conf --json
```

它比对 `nginx -T` 里所有 `client_max_body_size` 的最小值与策略最大值，并检查 `/media/` 是否带齐三个安全头。nginx 兜底明显过宽（> 策略 4×）只提醒不报错。

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
| 操作系统 | Debian / Ubuntu / 阿里云 Linux / RHEL 系 | 生产实机为 Alibaba Cloud Linux 3 |
| Docker | Docker Engine 24+ + compose 插件 | 由 `scripts/install-docker-host.sh` 安装（走阿里云 docker-ce 镜像源）；Docker 需 `enable`，重启机器后容器自动恢复 |
| Python / uv | 3.14 / 0.11+ | 只在构建镜像或本地开发时需要，生产机不需要 |
| Node.js | 22 | 只在构建镜像或本地构建前端时需要，生产机不需要 |
| nginx | 1.24+ | 留在宿主机，反代 `run/gunicorn.sock` |
| 数据库 | 缺省 SQLite（`db.sqlite3`）；可选 PostgreSQL 17+ | 留在宿主机，容器 `network_mode: host` 直连 `127.0.0.1`（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)） |
| 缓存 / 频道层 | 缺省无；可选 Redis 6+ | 留在宿主机；配 `REDIS_URL` 同时供缓存与 Channels 跨进程扇出；多 worker 前置条件 |
| 其他 | curl、tar、gzip、sqlite3、pg_dump（PG 部署） | 备份与排障用 |
| 磁盘 | 预留镜像与备份空间 | 镜像保留 3 个（`CLUB_DEPLOY_KEEP_IMAGES`）+ DB 快照保留 5 份（`CLUB_DEPLOY_KEEP_DUMPS`）+ 数据根（媒体等） |

端口与网络：容器内 Gunicorn 只监听 unix socket（`run/gunicorn.sock`），对外仅 Nginx 的 80/443。生产不需要开放其他端口。

## 3. 安装

生产采用**容器化运行**：应用镜像由 CI 构建，服务器上只保留运行时资产（`.env`、`data/`、`staticfiles/`、`run/`、`backups/`、`docker-compose.yml`、`scripts/`）。首次搭建：

```bash
# 1) 在服务器上取一份仓库（只用于安装脚本与 compose 文件）
git clone https://github.com/nhyzcms/club-management-website.git /tmp/club-install
cd /tmp/club-install

# 2) 体检，不改任何东西
sudo ./scripts/install-docker-host.sh --check

# 3) 安装 Docker、创建 clubdeploy、装 compose 与 deploy 脚本、起 club-deploy.timer
sudo ./scripts/install-docker-host.sh --yes --deploy-key-file /root/deploy.pub
```

脚本要求 `/opt/club/.env` 已存在（从旧部署沿用，或按 `.env.example` 填好后 `chmod 640`），并把属主设为 `root:clubdeploy` 供 `deploy.sh` 读取数据库口令。它刻意不动 nginx、PostgreSQL / pgbouncer / Redis（它们留在宿主机），也不删旧的 `/opt/club` 源码树。nginx 继续反代 `/opt/club/run/gunicorn.sock`，不需要改配置。

### 3.1 首次切流

```bash
sudo ./scripts/install-docker-host.sh --yes --cutover sha-<要上线的 sha>
```

切流会先 `stop` + `disable` 旧的 `club.service`（旧 unit 与容器抢同一个 unix socket），再拉起容器。旧的裸机安装路径（`scripts/install.sh`）仍保留在仓库里；每个版本发布时 Release 会附一份 `club-<sha>.tar.gz` + `.sha256`（供裸机 / 离线安装），但生产现行路径是容器。

### 3.2 CI 侧凭据

Deploy workflow 通过 SSH 执行受限制的 `deploy-wrapper.sh`（`restrict,command=...`，只放行 `stage` / `tick` / `status`）。仓库 Secrets 需要 `DEPLOY_HOST` / `DEPLOY_PORT` / `DEPLOY_USER` / `DEPLOY_SSH_KEY` / `DEPLOY_KNOWN_HOSTS`，完整步骤见 `deploy/README.md`。ghcr 拉取凭据见 §6.5。

### 3.3 安装后的收尾

```bash
# 1) 补可选凭据（邮件 / Turnstile / ghcr token），然后重建容器
sudo nano /opt/club/.env
sudo -u clubdeploy /opt/club/scripts/deploy.sh status           # 记下「运行中」的 tag
sudo -u clubdeploy /opt/club/scripts/deploy.sh now <记下的 tag>  # 用同一个 tag 重建容器

# 2) 登录 /admin/，把成员加入「社长」「信息组」组（没组 = 没权限）
# 3) /admin/ 的「站点策略」里调站点开关与限流额度（更新窗口已迁到 .env，见 §6）
```

## 4. 环境变量

全部通过 `.env` 管理（模板 `.env.example` 入库；`.env` 已 gitignore）。`start.sh` 不会自动从模板复制——`.env` 缺失时直接报错退出，避免把开发默认值带进生产；容器通过 compose 的 `env_file` 读取它。

| 变量 | 用途 | 生产 |
|---|---|---|
| `SECRET_KEY` | Django 签名密钥 | **必填**；`DJANGO_DEBUG=0` 且留空时进程拒绝启动（`ImproperlyConfigured`） |
| `DJANGO_DEBUG` | 调试开关 | 设 `0`（`.env` 由部署时填写 / 从旧部署沿用） |
| `ALLOWED_HOSTS` | 允许的 Host，逗号分隔 | **必填**（同上） |
| `FRONTEND_URL` | 邮件链接来源 | 建议填站点域名 |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | 163 邮箱账号与 **SMTP 授权码** | 按需；不配则邮件走 console 后端 |
| `NOTIFICATIONS_DELIVERY_ASYNC` | 通知外发投递模式 | 默认异步（进程内队列，失败自动退避重试）；`=0` 回退同步投递（见 [ADR-0024](../adr/0024-async-notification-delivery.md)） |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile | 按需；两项都空 = 关闭，只填一半也视为关闭 |
| `UPDATE_GITHUB_TOKEN` / `UPDATE_GITHUB_REPO` | 旧更新器凭据（更新器已删除）；仅 `scripts/install.sh` 的独立安装（拉 Release）沿用 | 可留空；容器部署不读。ghcr 凭据见 §6.5 |
| `DB_ENGINE` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | 数据库切换与连接 | 留空 = SQLite；`DB_ENGINE=postgresql` 启用 PostgreSQL；`DB_PORT` 可指向 pgbouncer（transaction pooling；服务端游标与自动 prepared statements 已在 settings 关闭） |
| `REDIS_URL` | 缓存 + 频道层 | 留空 = v1；配置后可用 `GUNICORN_WORKERS` >1 |
| `GUNICORN_WORKERS` | ASGI worker 数 | 默认 `1`；**须配 `REDIS_URL`** |
| `LOGIN_CHALLENGE` | 陌生设备二次验证开关 | 默认开启；线上异常可置 `0` 应急回滚（设备与登录事件照常记录） |
| `IP2REGION_DB` | 离线 IP 库路径 | 默认 `<安装目录>/data/ip2region_v4.xdb`；文件缺失时静默降级为只记 IP |

逐项默认值、派生逻辑与相关测试见[配置参考](../configuration.md)。部署相关的变量由 `deploy/docker-compose.yml` 与 `scripts/deploy.sh` 读取：`CLUB_IMAGE`（要运行的镜像 tag，`deploy.sh` 注入）、`CLUB_DEPLOY_WINDOW_START` / `CLUB_DEPLOY_WINDOW_END` / `CLUB_DEPLOY_TZ`（窗口，默认 `01:00` / `03:00` / `Asia/Shanghai`）、`CLUB_DEPLOY_KEEP_IMAGES`（默认 3）、`CLUB_DEPLOY_KEEP_DUMPS`（默认 5）、`CLUB_DEPLOY_HEALTH_TIMEOUT`（默认 90 秒）。前端构建期还可传 `AMAP_KEY` 注入高德地图 key（`AMAP_KEY=… npm run build`）；未设置时登录记录页降级为城市文字。

## 5. 日常服务管理

```bash
sudo -u clubdeploy /opt/club/scripts/deploy.sh status   # 版本 / 窗口 / 容器健康
sudo docker ps                                          # club-app 状态
sudo docker restart club-app                            # 重启（读 .env 变更）
sudo docker logs -f club-app                            # 跟日志
sudo docker logs club-app --tail 100 --no-pager
```

改 `.env` 后必须**重建容器**才生效（compose 的 `env_file` 只在创建时读取，
`docker restart` 不够）：

```bash
sudo -u clubdeploy /opt/club/scripts/deploy.sh status              # 先看当前是哪个 tag
sudo -u clubdeploy /opt/club/scripts/deploy.sh now sha-<当前sha>   # 用同一个 tag 重建
```

只改 nginx 配置时不必动容器：

```bash
sudo nginx -t && sudo systemctl reload nginx
```

容器内排障（镜像里没有 `ps`，用 `sh` + `/proc`）：

```bash
sudo docker exec -it club-app sh
sudo docker exec club-app python manage.py shell
```

> 旧的 `systemctl status|restart|stop club` 已失效：`club.service` 于 2026-11-20 删除。

维护拦截（写 `run/MAINTENANCE`，全站 503，含 `/admin/`）：

```bash
sudo docker exec club-app python manage.py maintenance on --message "机房维护，预计 30 分钟"
sudo docker exec club-app python manage.py maintenance status
sudo docker exec club-app python manage.py maintenance off
```

更新进行中执行 `on` 会记下 `resume_ops`，更新结束后自动恢复运维拦截；`off` 不会中止进行中的更新。

身份有效期兜底（撤销过期管理员、停用超期未认证账号；登录 / 请求时的惰性执行只覆盖来访问的账号，建议用 cron / systemd timer 定期兜底），并同时发**到期前提醒**（身份还剩两个月 / 一个月，站内通知；台账保证只发一次，见[身份认证](../guides/certification.md#到期前提醒降权预警)）：

```bash
sudo docker exec club-app python manage.py enforce_validity                 # 执行一次（含到期前提醒）
sudo docker exec club-app python manage.py enforce_validity --dry-run       # 只统计，不改动（提醒也不落库）
sudo docker exec club-app python manage.py enforce_validity --skip-notices  # 只做降权 / 停用，不发提醒
```

账号有效期说明群发（一次性运营动作：给全体启用用户发个性化站内私信 + 「收到新私信」通知；跳过发送者本人 / 已注销 / 停用账号，同一会话 `--dedupe-days` 天内重跑会跳过）：

```bash
sudo docker exec club-app python manage.py send_validity_broadcast --dry-run     # 只统计与预览，不落库
sudo docker exec club-app python manage.py send_validity_broadcast --from admin  # 发送者（缺省取最早创建的超级管理员）
sudo docker exec club-app python manage.py send_validity_broadcast --limit 5     # 限量试发
```

通知外发（邮件）默认**异步**投递（进程内队列 + 守护线程，失败自动退避重试、重启不丢，见 [ADR-0024](../adr/0024-async-notification-delivery.md)）——手动补投 / 排障入口：

```bash
sudo docker exec club-app python manage.py flush_notifications              # 排空内存队列 + 补投到期的待投递行
sudo docker exec club-app python manage.py flush_notifications --limit 500  # 限量（默认 200）
```

数据一致性与清理（B4 / B9 起）：

```bash
sudo docker exec club-app python manage.py check_profile_sync           # 体检：Profile 与 AccountIdentity / AccountLifecycle 行是否齐全（退出码 1 = 有缺口）
sudo docker exec club-app python manage.py check_profile_sync --fix     # 以新表补齐缺行
sudo docker exec club-app python manage.py prune_orphan_targets         # 默认预演：列出宿主已删的孤儿 ContentTarget
sudo docker exec club-app python manage.py prune_orphan_targets --apply # 确认后删除（可加 --kind=news 只处理一类）
```

B4 删掉 `Profile` 的旧列后，`check_profile_sync` 退化为「新表缺行体检」；`prune_orphan_targets` 处理裸 SQL、数据库级 CASCADE 与迁移删数据绕过 `post_delete` 留下的孤儿锚点（正常删除会自动清理）。

账号彻底删除（物理删除，不可恢复；日常优先用 Django 后台的「强制彻底删除」动作，命令行用于服务器侧应急）：

```bash
sudo docker exec club-app python manage.py hard_delete_account <用户名或id> [更多目标…]          # 预检：只打印目标与模式，不删除
sudo docker exec club-app python manage.py hard_delete_account <用户名或id> --mode keep --reason "冒用身份注册" --yes
sudo docker exec club-app python manage.py hard_delete_account <用户名或id> --mode purge --reason "垃圾账号" --yes
```

`--mode keep`（默认）保留内容并匿名化到墓碑账号；`--mode purge` 连内容一起删。`--yes` 必填，不加只预检。每次执行写 `AccountDeletionLog`（actor 记为 `cli`）；不会删除社员名册行，也不能删最后一个可用超级管理员。

问卷附件回收（审计 #271 起，匿名上传点落 `SurveyUpload` 台账；未被任何作答引用的孤儿文件可清，默认只预演）：

```bash
sudo docker exec club-app python manage.py sweep_survey_uploads             # 预演：列出超过 7 天且未被作答引用的文件
sudo docker exec club-app python manage.py sweep_survey_uploads --apply     # 确认后删除（文件 + 台账行）
sudo docker exec club-app python manage.py sweep_survey_uploads --days 14   # 放宽保留窗口（默认 7 天）
```

明信片照片回收（旧裸机安装会配 `club-postcard-gc.timer`；容器化宿主机没有这条 timer，需要时手动执行或自加 cron）：

```bash
sudo docker exec club-app python manage.py postcard_photo_gc
```

它做三件事：活动结束 → 照片文件全量清除（登记数据保留）；终态失败照片超 24h → 删文件；`pending` 卡死超 1h → 转人工复核。输出 JSON 统计（`ended_events_purged` / `ttl_purged` / `stale_pending_to_manual`）。

Nginx 侧：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 6. 升级流程

生产使用**容器部署**：CI 构建镜像 → 推 `ghcr.io` → 服务器上的定时器在维护窗口内切换容器。
服务器上**没有代码树、没有 `.venv`、没有 `.git`**——`/opt/club` 只剩运行时资产（`.env`、
`data/`、`staticfiles/`、`run/`、`backups/`、`docker-compose.yml`、`scripts/deploy.sh`）。

> 旧的「更新器定时轮询 GitHub Release 拉 `club-<sha>.tar.gz`」已于 2026-11-20 弃用；
> 更新器代码与 `UpdaterPolicy` 表已于 2026-11-21 彻底删除（迁移 `common/0023`）。
> 发行包只在**版本发布**时出一份：`ci.yml` 的 `release` job 把 `club-<sha>.tar.gz` +
> `.sha256` 挂到该 `vX.Y.Z` Release，供裸机 / 离线安装；生产升级不读它。

**版本与发布**：版本号遵循 SemVer（唯一真源 `pyproject.toml` 的 `version`，tag 形如 `v1.2.3`）。
发布 = 手动 dispatch `release.yml` → 开 `release/vX.Y.Z` PR → 评审合并即发布审批 →
`main` 上自动打 tag、建 GitHub Release、给镜像补版本 tag、滚动 Milestone。
细则见仓库根 `RELEASING.md`。**发布不等于上线**：生产切换仍由 Deploy 登记 + 夜间窗口执行。

**版本可见性**：镜像里带 CI 生成的 `build_info.json`，运行时经 `GET /version/` 暴露；
`channel=release` 且版本号等于刚发布的那个，才说明生产已切到该版本（`channel=dev` = 还在跑分支构建）。
`GET /changelog/` 同源给出该版本的社员版说明。排查「部署到底生效没」先看它，不必先 SSH。
容器内也可 `python manage.py version [--json]`。

**发布收尾漏跑时**：合并发布 PR 后若该提交上 **0 条 check-run**（GitHub 没收到这次 push），
tag / Release / Milestone 都不会自动发生——用 `gh workflow run release.yml --ref main -f finish=1`
补收尾，再 `gh workflow run image.yml --ref main` 补镜像（手动 dispatch 也会推 GHCR）。
补完确认 Deploy 把 `sha-<sha>` 写进待发布队列。

### 6.1 全链路

合并 PR 到 `main` 之后，流水线自动执行三步：

1. **CI** — 四道闸：`backend` / `frontend` / `frontend-test` / `e2e`。`e2e` 在 push `main` /
   `develop`、目标为 `main` 的 PR、`ci:full` 标签、以及涉前端的 PR→`develop` 时真跑；
   其余 PR 走 no-op（job 仍报 success，避免必需检查停在 skipped）。
2. **Image** — 多阶段构建镜像，跑冒烟（布局守卫 / `migrate` / `/site-policy/` 返回 JSON /
   SPA 入口含 `id="root"`），推 `ghcr.io/nhyzcms/club-management-website:sha-<sha>` 与 `:latest`。
3. **Deploy** — 通过 SSH 执行 `deploy.sh stage sha-<sha>`，**只拉镜像并登记，不切换**。

若这次提交正是版本发布（HEAD 带 `v*` tag），还会多一步：`ci.yml` 的 `release` job 打包
`club-<sha>.tar.gz` + `.sha256` 并挂到该版本 Release（每个版本一份；非版本提交只留一个 90 天的 workflow artifact）。

服务器上的 `club-deploy.timer` 每 5 分钟 tick 一次，只有落在窗口内才真正应用：

```
窗口（默认 [01:00, 03:00) Asia/Shanghai，由 .env 的
      CLUB_DEPLOY_WINDOW_START / CLUB_DEPLOY_WINDOW_END / CLUB_DEPLOY_TZ 控制）
  ① pg_dump 直连 5432 → backups/db/club-<时间戳>.sql.gz（保留 5 份）
  ② migrate
  ③ collectstatic → /opt/club/staticfiles（nginx 直出）
  ④ docker compose up -d --no-deps --force-recreate app
  ⑤ 健康检查（最多 90 秒）；失败自动回滚到上一个 tag
```

**为什么「登记」与「切换」分开**：镜像 300–500 MB，不必卡在窗口里拉；窗口内只剩重建容器
（5–15 秒）。上课时段合并 `main` 不会立刻重启线上。

### 6.2 手动操作

```bash
# 唯一权威状态源：当前运行版本 / 待发布 / 是否在窗口 / 容器健康
sudo -u clubdeploy /opt/club/scripts/deploy.sh status

# 立刻切换（忽略窗口）
sudo -u clubdeploy /opt/club/scripts/deploy.sh now sha-<sha>

# 只拉镜像登记，等窗口再切
sudo -u clubdeploy /opt/club/scripts/deploy.sh stage sha-<sha>

# 回滚到上一版（读 run/applied-release 的「上一版本」）
sudo -u clubdeploy /opt/club/scripts/deploy.sh rollback
```

`stage` / `apply` / `now` / `rollback` 都支持 `--dry-run`（只打印将执行什么）；
`apply` 支持 `--force`（忽略「已经是这个 tag」的跳过判断）。

### 6.3 窗口外想立刻上线

两个做法，按需选择：

- **改窗口**：临时把 `.env` 的 `CLUB_DEPLOY_WINDOW_START/END` 调到当前时段，tick 会在 5 分钟内
  接上；改完记得调回去。
- **直接 `now`**：`deploy.sh now sha-<sha>` 无视窗口，代价是那一下会重建容器（约 5–15 秒不可用）。

### 6.4 回滚

```bash
sudo -u clubdeploy /opt/club/scripts/deploy.sh rollback          # 上一版
sudo -u clubdeploy /opt/club/scripts/deploy.sh now sha-<旧sha>   # 指定任意历史 tag
```

镜像保留最近 3 个（`CLUB_DEPLOY_KEEP_IMAGES`，默认 3），数据库快照保留 5 份
（`CLUB_DEPLOY_KEEP_DUMPS`，默认 5）。超出后在每次 `apply` 时自动裁剪。

回滚**只换镜像，不还原数据库**。`apply` 失败时的自动回滚也不还原——迁移一旦写成，
旧镜像可能读不懂新 schema，这种情况应该从 `backups/db/` 手工恢复（见 §7）。

### 6.5 ghcr 凭据

镜像包是 **private**（公开仓库不代表包公开）。服务器上以服务账号完成一次登录，
凭据落在 `/home/clubdeploy/.docker/config.json`：

```bash
printf '%s' '<token>' | sudo -n -u clubdeploy docker login ghcr.io -u <用户名> --password-stdin
sudo -u clubdeploy docker pull ghcr.io/nhyzcms/club-management-website:sha-<sha>
```

token 需要 **Packages: Read** 权限，建议单独创建一个只带该权限的凭据，不要复用 `.env` 里的其他
token——权限不足时会得到 `manifest 403` / `pull denied`。

### 6.6 排障

```bash
curl -s https://<站点>/version/ | python3 -m json.tool     # 线上实际版本（channel / commit）
sudo -u clubdeploy /opt/club/scripts/deploy.sh status
sudo docker ps                                            # club-app 是否 healthy
sudo docker logs club-app --tail 100                       # 应用日志
sudo tail -50 /var/log/club-deploy.log                     # 部署流水日志
sudo journalctl -u club-deploy.timer -n 50 --no-pager      # 定时器
```

容器 `restart: unless-stopped`，Docker 已 `enable`——**重启机器后站点会自动回来**，
不需要 `systemctl start club`（该 unit 已删除）。

### 6.7 预演环境（test）

在合并进 `main` 之前点一遍真实页面，用容器化预演环境，不另开分支。它跑的是 `develop` 的镜像，
数据面与生产隔离（库 `club_test`、Redis db 1、`/opt/club-test/{data,staticfiles,run}`）。

```bash
sudo scripts/test-env.sh init              # 一次性：建目录 / 派生 .env / 建 club_test 库 / 装 nginx 站点
sudo scripts/test-env.sh up sha-<sha>      # 拉起某个 develop 提交的镜像
ssh -N -L 8080:127.0.0.1:8080 nhyz-prod    # 另开终端；浏览器 http://127.0.0.1:8080/
sudo scripts/test-env.sh status|logs|down  # down 停掉保数据；reset --yes 停掉并清空
```

容器绑 `127.0.0.1:18080`，nginx 在 `127.0.0.1:8080` 反代，**不进安全组、不需要证书**——
该环境 `DJANGO_DEBUG=1`，debug 页会带 traceback 与 settings 片段，只应通过 SSH 隧道访问。
已知取舍与四个踩过的坑见 `deploy/README.md` 与 `CONTRIBUTING.md`。

## 7. 备份与恢复

### 7.1 数据面

| 内容 | 位置 | 说明 |
|---|---|---|
| 数据库（SQLite） | `<安装目录>/db.sqlite3` | 缺省部署的全部业务数据 |
| 数据库（PostgreSQL） | 本机 `club` 库（与站点同机） | `DB_ENGINE=postgresql` 时的全部业务数据 |
| 公开媒体 | `<数据根>/media/` | 头像、新闻封面、活动图片、教程、附件、考试误刊等 |
| 私有媒体 | `<数据根>/private_media/` | 身份证明（`IdentityProof`），**不在** `MEDIA_ROOT` 内，由鉴权视图服务 |
| 离线 IP 库 | `<安装目录>/data/ip2region_v4.xdb`（或 `IP2REGION_DB` 指向） | 约 11 MB，**不入 git**；换机时需单独放回。缺失时登录事件只记 IP、不解析城市 |
| App 分发 | `<数据根>/app-update/` | App 更新产物（manifest.json / latest.apk），nginx `/app-update/` 只读服务 |
| DB 快照 | `<安装目录>/backups/db/club-<时间戳>.sql.gz` | `deploy.sh apply` 在 `migrate` 前自动 `pg_dump`（PostgreSQL；直连 5432，不走 pgbouncer 6432），保留 5 份。SQLite 部署不自动备份，需手工 `.backup` |

> 数据根（`<数据根>`）：缺省 = 安装目录本身；启用统一数据根后为 `<安装目录>/data`（见[统一数据根](data-root.md)）。
>
> **备份权限**：`install-docker-host.sh` 把 `run/`、`backups/` 交给 `clubdeploy`，`.env` 设为 `640 root:clubdeploy`。备份含密码哈希、邮箱与业务数据，不要放宽这些权限。

容器只挂载 `data/`、`staticfiles/`、`run/` 与 `.env`；重建镜像不会碰这些目录，但**也不会替你备份**——`media` / `private_media` / `app-update` 需要自行归档。

### 7.2 手动备份

SQLite 用 `.backup` 而不是 `cp`（运行中的库可能有未落盘事务）：

```bash
cd /opt/club
sqlite3 db.sqlite3 ".backup '/opt/club/backups/db-manual-$(date +%Y%m%d-%H%M%S).sqlite3'"
tar -czf backups/data-$(date +%Y%m%d).tar.gz data/media data/private_media   # 未启用数据根的旧布局：去掉 data/ 前缀
```

PostgreSQL 用 `pg_dump`（普通 SQL 格式，可直接 `psql -f` 还原）：

```bash
cd /opt/club
PGPASSWORD='<DB_PASSWORD>' pg_dump -h 127.0.0.1 -U club --clean --if-exists --no-owner --no-acl \
  -f "backups/db-manual-$(date +%Y%m%d-%H%M%S).pg.sql" club
tar -czf backups/data-$(date +%Y%m%d).tar.gz data/media data/private_media   # 未启用数据根的旧布局：去掉 data/ 前缀
```

建议保留最近 7–30 天版本，并同步到对象存储或 NAS。`deploy.sh` 每次 `apply` 前会自己 `pg_dump` 到 `backups/db/club-<时间戳>.sql.gz`，保留份数由 `CLUB_DEPLOY_KEEP_DUMPS`（默认 5）控制。

### 7.3 恢复

**数据库（SQLite）**：

```bash
sudo docker stop club-app
cd /opt/club
rm -f data/db.sqlite3-journal data/db.sqlite3-wal data/db.sqlite3-shm
cp backups/db-<时间戳>.sqlite3 data/db.sqlite3
sudo docker start club-app
```

> 容器内进程以 root 运行，文件属主保持 root 即可；裸机部署仍为服务用户 `club`。

**数据库（PostgreSQL）**：

```bash
sudo docker stop club-app
cd /opt/club
PGPASSWORD='<DB_PASSWORD>' psql -h 127.0.0.1 -U club -v ON_ERROR_STOP=1 \
  -f backups/db/<文件>.sql club
sudo docker start club-app
```

**媒体**：解包归档到数据根对应位置（`<数据根>/media`、`<数据根>/private_media`），属主保持服务用户。

**代码**：不要手工解包。用 `deploy.sh now sha-<sha>` 切到指定镜像（见 §6.4），它会把容器整棵代码树换成该 tag 的镜像。

恢复后核对 `sudo -u clubdeploy /opt/club/scripts/deploy.sh status` 与关键页面（首页、`/admin/`、登录后 `/ws/messaging/` 握手）。

## 8. 常见故障与排查

### 8.1 访问 502 Bad Gateway

常见原因：Gunicorn 未启动 / 崩溃；`run/gunicorn.sock` 不存在或权限不对；SELinux 未打标签（阿里云 / RHEL 常见）。

```bash
sudo -u clubdeploy /opt/club/scripts/deploy.sh status
sudo docker ps -a --filter name=club-app
sudo docker logs club-app --tail 100
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
sudo docker exec club-app python manage.py collectstatic --noinput
```

再检查 `STATIC_ROOT`（`staticfiles/`）、`MEDIA_ROOT`（数据根下 `media/`，见[统一数据根](data-root.md)）与 Nginx 的 `location /static/`、`location /media/` 别名是否与安装目录 / 数据根一致。前端产物打包在镜像里，宿主机上没有 `frontend/dist`——首页白屏先看 `sudo docker logs club-app` 与镜像冒烟结果。

### 8.4 `database is locked`

SQLite 在并发写入时的典型问题：

- SQLite 部署的契约是 **`--workers 1`**；要加 worker 先上 Redis 频道层（[ADR-0021](../adr/0021-postgresql-redis-and-multiworker.md)），并建议同时切 PostgreSQL（SQLite 多写者）。
- 更新流程里 `migrate` 与 web 请求可能短暂并存，维护页正是为此先把访问拦下来（`drain` 步骤）——不要绕过维护旗标手工 `migrate`。
- 避免大量热点写操作同时发生；必要时错峰批量操作。

### 8.5 WebSocket 连不上 / 约一分钟断一次

页面功能不受影响（评论、私信、通知走 HTTP，只是不实时推）：

- 站点配置缺 `proxy_http_version 1.1` 或 `Upgrade` / `Connection` 头（**升级流程不会改 nginx**）。
- 只改了 80 的 `server`，443 块没有同一套反代头。
- `start.sh` 还是旧的 WSGI / 多 worker 写法：须为 `UvicornWorker`、`--workers 1`、`config.asgi:application`。
- 约 60 秒断一次：补 `proxy_read_timeout 7d; proxy_send_timeout 7d;`。
- 检查 `AllowedHostsOriginValidator` 是否因 `ALLOWED_HOSTS` 不含域名而拒绝握手。

### 8.6 容器升级不生效

- `Deploy` 失败 → 镜像没登记：看 Actions 的 Deploy run，多半是 SSH 或 `docker pull` 报错。
- 登记了但没切：`deploy.sh status` 看「待发布」是否为空、当前是否在窗口外。窗口外只登记不切换是设计行为。
- 窗口内也没切：`sudo journalctl -u club-deploy.timer -n 50 --no-pager`，再看 `/var/log/club-deploy.log`。
- `pull denied` / `manifest 403`：ghcr 凭据失效或缺 Packages:Read（见 §6.5）。
- 健康检查失败会自动回滚到上一 tag，日志里能看到 `回滚`；此时站点应仍可用，但版本没变。
- 想确认当前版本：`deploy.sh status` 的第一行，或 `cat /opt/club/run/applied-release`。

### 8.7 站点一直 503（维护页不撤）

```bash
cd /opt/club
set -a; . ./.env; set +a
sudo docker exec club-app python manage.py maintenance status
```

`reason=update` 说明有更新 / 回滚卡住（旧更新器时代遗留的旗标；容器部署不写它）：看 `sudo docker logs club-app --tail 200` 与 `sudo tail -100 /var/log/club-deploy.log`，确认后用 `deploy.sh now <tag>` 或 `deploy.sh rollback` 收尾；必要时 `maintenance off` 强制撤下（注意：若更新仍在进行，`off` 只取消「结束后的运维拦截」，不中止更新）。

## 9. 监控与巡检

```bash
sudo docker logs -f club-app               # 应用日志（web）
sudo journalctl -u club-deploy.timer -f    # 定时器 tick 日志
sudo tail -f /var/log/nginx/error.log      # Nginx 错误
```

建议关注：容器健康（`sudo docker ps --filter name=club-app` / `deploy.sh status`）、`run/applied-release` 是否与预期版本一致、`backups/db/` 占用与快照新鲜度、登录失败与限流命中、磁盘余量、`/admin/` 操作记录。

## 10. 发布前 / 定期检查清单

发布前：

- [ ] `.env` 完整（`SECRET_KEY`、`ALLOWED_HOSTS`、`FRONTEND_URL` 非空；`DJANGO_DEBUG=0`）
- [ ] `ALLOWED_HOSTS` 含真实域名（含即将启用的新域名）
- [ ] Nginx 上游为 HTTP/1.1 + `Upgrade` / `Connection`；有 TLS 的 443 块同样具备
- [ ] `deploy.sh status` 正常（容器 healthy、无异常待发布）
- [ ] 镜像冒烟通过（CI 已断言 SPA 入口含 `id="root"`、`/site-policy/` 返回 JSON）
- [ ] 关键页面可开；登录后 `/ws/messaging/` 能握手；教室看板 `/ws/exam-board/` 能连

定期（建议每周）：

- [ ] 手工备份数据库与数据根（`data/`，含 `media` / `private_media`），并验证归档可解
- [ ] 检查 `backups/` 磁盘占用与 `CLUB_DEPLOY_KEEP_IMAGES` / `CLUB_DEPLOY_KEEP_DUMPS` 设置
- [ ] 复核 `/admin/` 后台账号与组成员（离职 / 换届后及时回收）
- [ ] 查看站点策略是否仍符合当前运营需要（注册开关、限流额度、更新窗口）
