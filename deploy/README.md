# 容器化部署（生产）

从「GitHub Release + 更新守护进程」改为「CI 构建镜像 → 推 ghcr.io → 服务器拉取容器运行」。

## 为什么换

旧的更新器有两个硬伤：

1. **下载慢且脆**：每次 113 MB 的 tar.gz 走 GitHub → 阿里云的直连，实测 12–24 KB/s，
   要靠隧道代理才勉强到 300 KB/s；中途断一次就得续传。
2. **不是原子的**：解包到 staging 后按目录镜像替换站点文件，回滚依赖备份的数据库快照。

换成镜像后：拉取 7.7 MB/s（实测），版本以镜像 tag 标识，回滚就是 `docker run` 另一个 tag。

## 结构

```
push main ──► CI（backend/frontend/frontend-test/e2e）
                 │
                 ▼
            Image workflow
            多阶段构建 → 冒烟测试 → 推 ghcr.io:sha-<sha> + :latest
                 │
                 ▼
            Deploy workflow
            SSH 执行 `stage sha-<sha>`（只登记，不切换）
                 │
                 ▼
            生产机 club-deploy.timer（每 5 分钟）
            在窗口 [01:00, 03:00) Asia/Shanghai 内 apply：
            pg_dump → migrate → collectstatic → 重建容器 → 健康检查
```

只容器化 Django 应用。nginx、PostgreSQL、pgbouncer、Redis 仍在宿主机上，
容器用 `network_mode: host`，所以 `.env` 里的 `127.0.0.1:6432` / `127.0.0.1:6379` 一个字节都不用改。

挂载点与宿主机同名（`/opt/club/data`），因为 `.env` 里 `CLUB_DATA_DIR=/opt/club/data` 是绝对路径——
同名挂载才能让同一份 `.env` 在容器内外都成立。

## 首次搭建

### 1. 生成部署密钥（本地）

```bash
ssh-keygen -t ed25519 -N '' -C 'gha-deploy' -f ~/.ssh/club_deploy
```

### 2. 服务器初始化

把仓库的 `scripts/` 与 `deploy/` 传到服务器（或先 `git clone` 一份到 `/tmp`），然后：

```bash
sudo ./scripts/install-docker-host.sh --check          # 先体检，不改任何东西
sudo ./scripts/install-docker-host.sh --yes --deploy-key-file /root/club_deploy.pub
```

它会：装 Docker Engine（走阿里云镜像源，Alinux3 自带仓库里只有 podman）、
创建 `clubdeploy` 用户、装 compose 文件与 deploy 脚本、起 `club-deploy.timer`、
把公钥写进 `clubdeploy` 的 `authorized_keys`（`restrict` + 强制命令）。

### 3. GitHub Secrets

| Secret | 值 |
|---|---|
| `DEPLOY_HOST` | `8.153.145.175` |
| `DEPLOY_PORT` | `22`（可省略，默认 22） |
| `DEPLOY_USER` | `clubdeploy`（可省略） |
| `DEPLOY_SSH_KEY` | `~/.ssh/club_deploy` 的**私钥**全文 |
| `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan -p 22 8.153.145.175` 的输出 |

`DEPLOY_KNOWN_HOSTS` 必须是真的扫出来的值，不要用 `StrictHostKeyChecking=no` 绕。

### 4. 切流

```bash
sudo ./scripts/install-docker-host.sh --yes --cutover sha-<要上线的 sha>
```

这一步会 `systemctl stop club.service && systemctl disable club.service`——
旧 unit 和容器会抢同一个 `/opt/club/run/gunicorn.sock`，必须先停。

nginx **不需要改**：`location /` 依然反代那个 socket。

## 日常

合并 PR → CI 绿 → 镜像构建成功 → Deploy workflow 自动登记 → 当夜窗口内切换。

想立刻上线：

```bash
sudo -u clubdeploy /opt/club/scripts/deploy.sh now sha-<sha>
```

查看状态：

```bash
sudo -u clubdeploy /opt/club/scripts/deploy.sh status
```

## 预演环境（test）

在合并进 `main` 之前点一遍真实页面。跑的是 `develop` 的镜像，数据面与生产隔离。

```bash
# 一次性初始化：建目录、派生 .env、建 club_test 库、装 nginx 站点
sudo scripts/test-env.sh init

# 拉起某个提交（develop 的 sha，镜像由 Image workflow 构建）
sudo scripts/test-env.sh up sha-abc1234

# 开发者本机开隧道（不需要安全组 / 域名 / 证书）
ssh -N -L 8080:127.0.0.1:8080 nhyz-prod
# 浏览器打开 http://127.0.0.1:8080/

sudo scripts/test-env.sh status
sudo scripts/test-env.sh logs
sudo scripts/test-env.sh down          # 停掉，数据保留
sudo scripts/test-env.sh reset --yes   # 停掉并清空数据
```

### 隔离面

| 资源 | 生产 | test |
|---|---|---|
| 数据库 | `club` | `club_test` |
| Redis | db 0 | db 1 |
| 媒体 | `/opt/club/data` | `/opt/club-test/data` |
| 静态 | `/opt/club/staticfiles` | `/opt/club-test/staticfiles` |
| 端口 | 80/443（nginx） | `127.0.0.1:8080`（nginx）→ `127.0.0.1:18080`（容器） |
| 进程 | `club-app` | `club-test-app`（`mem_limit: 400m`） |

### 为什么不开公网

`DJANGO_DEBUG=1` 会把 traceback、局部变量、settings 片段打进错误页。这个环境**只绑回环**，
通过 SSH 隧道访问，既不用开安全组，也不用心疼没人给测试站发证书。

如果哪天真要对外演示，先把 `.env` 里 `DJANGO_DEBUG` 改成 `0`，再考虑开端口。

### 已知取舍

- 容器 `restart: "no"`：机器重启后 test 环境不会自己起来。刻意的——它会占 400 MB 内存，
  而且跑的是旧提交，自动拉起只会让人误以为线上就是这个版本。
- 数据保留到下次 `reset`。想复现某个 bug 就别急着 reset，先 `down`。

## 回滚

```bash
sudo -u clubdeploy /opt/club/scripts/deploy.sh rollback
```

只回退**代码**。数据库迁移是单向的——如果新版本跑了破坏性迁移，
需要用 `--restore-db=` 指定 `backups/db/` 里的快照：

```bash
sudo -u clubdeploy /opt/club/scripts/deploy.sh rollback sha-<旧sha> --restore-db=/opt/club/backups/db/club-20261120-020001.sql.gz
```

每次 apply 之前都会自动 `pg_dump` 一份（保留最近 5 份）。

## 已知取舍

- **容器内以 root 运行**。与旧 systemd unit（`User=root`）一致，不是本次放宽；
  改成非 root 需要先统一 `data/`、`staticfiles/`、`run/` 的 uid，属于单独迁移。
- **切换有 5–15 秒不可用**。重建容器期间 nginx 会拿到 502。没有做蓝绿双容器，
  因为 1.87 GB 内存同时跑两份 Django 不划算。
- **`clubdeploy` 在 docker 组里，等价 root**。真正的约束是那条密钥被强制到
  `deploy-wrapper.sh`，只能执行 `stage` / `tick` / `status`。
- **旧的 `/opt/club` 源码树没删**。回滚要它。确认容器稳定运行一段时间后再单独清理。
