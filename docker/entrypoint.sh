#!/usr/bin/env bash
# 容器入口：按子命令分派，默认拉起生产进程。
#
# 刻意复用 start.sh 而不是重写一套 gunicorn 参数——裸机安装与容器安装
# 因此走同一条启动路径，参数漂移只可能发生在一个地方。
set -euo pipefail

cd /app

_load_env_if_present() {
  if [ -f /app/.env ]; then
    set -a
    # shellcheck disable=SC1091
    . /app/.env
    set +a
  fi
}

case "${1:-web}" in
  web)
    # 生产：unix socket + systemd 式生命周期（start.sh 内部会按需拉更新守护进程，
    # 容器里由 CLUB_SPAWN_UPDATER=0 关掉——更新改由 CD 流水线负责）
    exec ./start.sh
    ;;

  web-tcp)
    # 仅用于 CI 冒烟：不依赖 unix socket，直接监听 TCP
    _load_env_if_present
    exec ./.venv/bin/gunicorn \
      -k uvicorn.workers.UvicornWorker \
      --workers "${GUNICORN_WORKERS:-1}" \
      --bind "0.0.0.0:${PORT:-8000}" \
      --access-logfile - --error-logfile - \
      config.asgi:application
    ;;

  migrate)
    shift
    _load_env_if_present
    exec ./.venv/bin/python manage.py migrate --noinput "$@"
    ;;

  collectstatic)
    shift
    _load_env_if_present
    exec ./.venv/bin/python manage.py collectstatic --noinput "$@"
    ;;

  check)
    shift
    _load_env_if_present
    exec ./.venv/bin/python manage.py check "$@"
    ;;

  shell)
    shift
    _load_env_if_present
    exec ./.venv/bin/python manage.py shell "$@"
    ;;

  *)
    exec "$@"
    ;;
esac
