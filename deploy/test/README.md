# test 环境（测试服务器）

一条独立的长期分支 `test-env` 维护的完整测试栈：**应用 + PostgreSQL + Redis 全部在容器里**，
不经过 nginx，直接把 `52603` 发布到公网，Django 以 `DEBUG=1` 运行，整站套一层 HTTP Basic 登录。

用于在合并进 `main` 之前点真实页面、看真实报错。`develop` 每次前进，CI 会自动把
`test-env` 更新并部署到这套环境（`.github/workflows/test-env.yml`）。

## 访问

- 地址：<http://8.153.145.175:52603/>
- 账号密码：服务器 `/opt/club-test/.env` 里的 `TEST_BASIC_AUTH_USER` / `TEST_BASIC_AUTH_PASSWORD`
- 探活：<http://8.153.145.175:52603/healthz/>（豁免 Basic，只回 `{"status": "ok"}`）
- 环境提示：页面顶部常驻 **TEST 横幅**（compose 里 `SITE_ENV=test`，由 `/version/`
  的 `environment` 字段驱动）；生产站页脚有「测试环境」入口

> `DEBUG=1` 的错误页会带 traceback、局部变量与 settings 片段。Basic 认证只负责
> 「谁能看」，**不加密传输**（明文 HTTP）。别在里面填真实敏感数据，凭据也要定期换。

## 结构

```
develop ──push──► Actions「Test Env」
                   │ 1. merge develop → test-env（长期分支）并 push
                   │ 2. 构建镜像 :test-<sha12> + :test
                   │ 3. ssh sync  ← deploy/test/docker-compose.yml + scripts/
                   │ 4. ssh deploy test-<sha12>
                   ▼
             /opt/club-test（服务器）
               ├── docker-compose.yml   ← CI 覆盖
               ├── .env                 ← 服务器上生成，唯一真源
               ├── data/                ← media / private_media
               ├── staticfiles/         ← collectstatic 输出
               ├── pgdata/              ← PostgreSQL 数据
               └── scripts/{deploy.sh,deploy-wrapper.sh,sync.sh}
```

`test-env` 分支只放这套环境的东西（`deploy/test/`），业务代码一律从 `develop` 合并进来。
**不要直接往 `test-env` 提交功能代码**；改了 `deploy/test/` 以外的文件，下次同步会与 develop 冲突。

## 与生产的隔离面

| 资源 | 生产 | test |
|---|---|---|
| compose project | `club` | `club-test` |
| 应用 | `club-app`（host 网络，nginx 反代 unix socket） | `club-test-web`（bridge，直发 52603） |
| 数据库 | 宿主机 PG `club`（经 pgbouncer 6432） | 容器内 PG `club_test`（直连 5432） |
| Redis | 宿主机 `127.0.0.1:6379/0` | 容器内 `redis:6379/0` |
| 媒体 / 静态 | `/opt/club/*` | `/opt/club-test/*` |
| nginx | 有 | **无**（Django 自己服务 `/static/`、`/media/`） |
| 访问控制 | 无（公网站点） | HTTP Basic（应用层中间件） |

停掉、重建、删掉 `/opt/club-test` 都不会碰到生产。

## 服务器运维

```bash
# 状态（当前 last-good / 容器 / 探活）
sudo -u clubdeploy /opt/club-test/scripts/deploy.sh status

# 跟日志
sudo -u clubdeploy /opt/club-test/scripts/deploy.sh logs

# 手动部署某个 tag（通常只有排查时用）
sudo -u clubdeploy /opt/club-test/scripts/deploy.sh deploy test-<sha12>

# 停栈（数据保留）
sudo -u clubdeploy /opt/club-test/scripts/deploy.sh down
```

部署失败会自动回滚到 `/opt/club-test/.last-good` 里的上一版，并把 web 日志尾部打到输出。

## 首次搭建（已经做过一次，重建时照此执行）

1. **建长期分支**（从 develop 切，只加 `deploy/test/`）：

   ```bash
   git fetch origin develop
   git checkout -b test-env origin/develop
   mkdir -p deploy/test/scripts
   # 放入本目录的 docker-compose.yml / docker-compose.debug.yml / .env.example /
   # README.md 与 scripts/*.sh
   git add deploy/test && git commit -m "chore(test): test 环境容器化与自动部署" && git push -u origin test-env
   ```

2. **服务器目录与配置**：

   ```bash
   sudo mkdir -p /opt/club-test/{data,staticfiles,pgdata,scripts}
   sudo chown -R clubdeploy:clubdeploy /opt/club-test
   # CI 的 sync 会覆盖 compose 与 scripts/，所以这两个位置必须让 clubdeploy 可写；
   # data / staticfiles / pgdata 保持 root（应用容器以 root 写，pgdata 归 uid 70）。
   sudo chown root:root /opt/club-test/data /opt/club-test/staticfiles /opt/club-test/pgdata
   sudo chown -R 70:70 /opt/club-test/pgdata
   # .env 由 clubdeploy 持有，600；模板见 deploy/test/.env.example
   sudo -u clubdeploy install -m 600 /dev/null /opt/club-test/.env
   sudo -u clubdeploy vim /opt/club-test/.env      # 填 SECRET_KEY / DB_PASSWORD / Basic 凭据
   sudo install -m 755 deploy/test/scripts/*.sh /opt/club-test/scripts/
   sudo chown clubdeploy:clubdeploy /opt/club-test/scripts/*.sh
   ```

3. **受限 SSH key**（CI 用，与生产 key 分开）：

   ```bash
   ssh-keygen -t ed25519 -N '' -C 'gha-test-env' -f ~/.ssh/club_test_env
   # 公钥写进 clubdeploy 的 authorized_keys，强制走 wrapper：
   echo 'restrict,command="/opt/club-test/scripts/deploy-wrapper.sh" '"$(cat ~/.ssh/club_test_env.pub)" \
     | sudo tee -a /home/clubdeploy/.ssh/authorized_keys
   ```

4. **仓库 secrets / 变量**：

   ```bash
   gh secret set TEST_SSH_KEY        < ~/.ssh/club_test_env
   gh secret set TEST_SSH_HOST       --body 8.153.145.175
   gh secret set TEST_SSH_PORT       --body 22
   gh secret set TEST_SSH_USER       --body clubdeploy
   gh secret set TEST_SSH_KNOWN_HOSTS --body "$(ssh-keyscan -p 22 8.153.145.175 2>/dev/null)"
   gh variable set TEST_ENV_ENABLED --body true    # 最后一步：打开自动部署
   ```

5. **停掉旧的 nginx 测试站点**（旧配置监听 127.0.0.1:8080 并反代到 18080，已废弃；
   新版不经过 nginx，摘掉它避免端口与维护状态混淆）：

   ```bash
   sudo rm /etc/nginx/conf.d/club-test.conf
   sudo nginx -t && sudo systemctl reload nginx
   ```

6. **确认安全组放行 52603**（阿里云控制台；已放行则跳过）。

## 冲突处理

自动合并失败时 job 会红，并自动开一个「test-env 同步 develop 冲突」issue。本地解决：

```bash
git fetch origin
git checkout -B test-env origin/test-env
git merge origin/develop
# deploy/test/ 的冲突以 test-env 侧为准；其他路径按正常 Git Flow 解决
git push origin test-env
```

推完到 Actions 手动跑一次 `Test Env`，或等下一次 `develop` 推送。

## 调试包

`Release` workflow 会把「源码 + 便携 compose」打成 `club-<version>-debug.tar.gz`
挂到对应 Release。解压后：

```bash
cp deploy/test/.env.example .env    # 改 SECRET_KEY / DB_PASSWORD / Basic 凭据
# --env-file 不能省：compose 默认只在 deploy/test/ 找 .env，变量插值会失败（实测）。
docker compose --env-file .env -f deploy/test/docker-compose.debug.yml run --rm web migrate
docker compose --env-file .env -f deploy/test/docker-compose.debug.yml run --rm web collectstatic
docker compose --env-file .env -f deploy/test/docker-compose.debug.yml up -d --build
# http://127.0.0.1:52603/
```

数据落在解压目录的 `data/`、`staticfiles/`、`pgdata/`。`docker-compose.yml`（不带 `.debug`）
是服务器用的：镜像走 GHCR、路径固定在 `/opt/club-test`，不要拿它在本机跑。

## 已知取舍

- **PG / Redis / web 都在同一台机器上**：隔离的是「容器与数据面」，不是物理机。
  测试负载不大（内存上限 450m + 320m + 96m），不会把生产挤到 OOM；真压测请另找机器。
- **镜像来自 Docker Hub 的 DaoCloud 镜像站**（`docker.m.daocloud.io/library/...`）：
  本机到 Docker Hub 直连 12s 超时，实测该镜像站可拉。镜像站失效时改 compose 里的两行即可。
- **`restart: unless-stopped`**：机器重启后 test 环境会自己起来。它现在跟的是 develop，
  不再是「一份旧提交」，所以自动拉起是合理的。
- **SQLite 不再是选项**：`.env` 里 `DB_ENGINE=postgresql` 指向容器内 PG；本地想用 SQLite
  就直接跑 `manage.py runserver`，不要用这套 compose。
