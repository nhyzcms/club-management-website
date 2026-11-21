#!/usr/bin/env bash
# start.sh — 启动生产 ASGI（Gunicorn + UvicornWorker）。
#
# 设计：路径全部相对本脚本（仓库根），不硬编码 /srv/club。
#   - 由 systemd unit `club.service` 的 ExecStart 调用（Type=notify）；
#   - 也可手动 ./start.sh 前台跑（Ctrl-C 停），便于排障。
# 用 `exec` 让 gunicorn 顶替本 shell 成为 unit 主进程，sd_notify 才工作。
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

# 更新守护进程已移除（2026-11-21）：生产改为容器化 CD
# （CI 构建镜像 → 推 ghcr.io → Deploy workflow 登记 → 窗口内 deploy.sh 切换）。
# 旧更新器会改写宿主机 /opt/club 代码树，和「容器跑只读镜像」的语义直接冲突，
# 所以连同 common/updater.py、scripts/updater.py 与 UpdaterPolicy 表一起删掉了。

exec "$DIR/.venv/bin/gunicorn" \
  -k uvicorn.workers.UvicornWorker \
  --workers "${GUNICORN_WORKERS:-1}" \
  --bind "unix:$DIR/run/gunicorn.sock" \
  --access-logfile - --error-logfile - \
  config.asgi:application
