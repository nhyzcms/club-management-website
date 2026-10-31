#!/usr/bin/env bash
# start.sh — 启动生产 ASGI（Gunicorn + UvicornWorker），并拉起同生命周期的更新守护进程。
#
# 设计：路径全部相对本脚本（仓库根），不硬编码 /srv/club。
#   - 由 systemd unit `club.service` 的 ExecStart 调用（Type=notify）；
#   - 也可手动 ./start.sh 前台跑（Ctrl-C 停），便于排障。
# 用 `exec` 让 gunicorn 顶替本 shell 成为 unit 主进程，sd_notify 才工作。
# 更新进程是 gunicorn 的兄弟（fork 后 exec）：停 club 时 systemd 清整个 cgroup，
# 不另写 club-updater.service。Apply 时对父进程 SIGHUP，避免 restart 把自己杀掉。
# ADR 0015/0021：InMemory 频道层不能跨进程扇出 → 未配 REDIS_URL 时保持 worker=1；
# 配好 Redis 频道层后可用 GUNICORN_WORKERS 提高并发（默认仍 1）。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# .env 必须由 install.sh / 运维显式生成：不再从模板自动复制。
# 自动复制会把模板里的开发默认值（含 DJANGO_DEBUG）原样带进生产（审计 H-6）。
if [ ! -f .env ]; then
  echo "缺少 $DIR/.env：生产请先运行 scripts/install.sh；本地开发请 cp .env.example .env 并填写 SECRET_KEY / DJANGO_DEBUG=1。" >&2
  exit 1
fi
# 导出 .env 供 gunicorn/Django 读（手动单跑时需要；systemd 调用时也幂等）。
set -a; . ./.env; set +a

# socket 目录（相对仓库根）；systemd unit 与 nginx 都指向这里。
mkdir -p "$DIR/run"

# 与 Gunicorn 同生共死。CLUB_SPAWN_UPDATER=0 可关（排障只起 web）。
# CLUB_UPDATER_PROXY 可选（如 http://127.0.0.1:7891）：只注入更新器进程，
# 给 GitHub API/Release 下载加速；gunicorn/Django 不受影响（业务出站不走代理）。
if [ "${CLUB_SPAWN_UPDATER:-1}" != "0" ] && [ -x "$DIR/.venv/bin/python" ]; then
  export CLUB_UPDATER_SPAWNED=1
  if [ -n "${CLUB_UPDATER_PROXY:-}" ]; then
    HTTPS_PROXY="${CLUB_UPDATER_PROXY}" \
    HTTP_PROXY="${CLUB_UPDATER_PROXY}" \
    NO_PROXY="${CLUB_UPDATER_NO_PROXY:-127.0.0.1,localhost}" \
    "$DIR/.venv/bin/python" "$DIR/scripts/updater.py" &
  else
    "$DIR/.venv/bin/python" "$DIR/scripts/updater.py" &
  fi
fi

exec "$DIR/.venv/bin/gunicorn" \
  -k uvicorn.workers.UvicornWorker \
  --workers "${GUNICORN_WORKERS:-1}" \
  --bind "unix:$DIR/run/gunicorn.sock" \
  --access-logfile - --error-logfile - \
  config.asgi:application
