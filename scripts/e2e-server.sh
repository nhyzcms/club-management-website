#!/usr/bin/env bash
# E2E 专用服务编排（Playwright webServer 调用）：
#   独立 SQLite（run/e2e.sqlite3，每次重建）→ migrate → seed_e2e → Django runserver。
# Django 直接托管 frontend/dist（SPA / API / media 同源）。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f frontend/dist/index.html ]; then
  echo "缺少前端构建产物：请先 cd frontend && npm run build" >&2
  exit 1
fi

export DJANGO_DB_FILE="${DJANGO_DB_FILE:-run/e2e.sqlite3}"
# E2E 关闭「陌生设备二次验证」：seed 账号带安全问题，否则 API 登录只拿到 202 挑战、
# storageState 无会话，全部登录态用例会级联失败。挑战流程本身由单测覆盖。
export LOGIN_CHALLENGE=0
mkdir -p run
rm -f "$DJANGO_DB_FILE"

uv run python manage.py migrate --noinput
uv run python manage.py seed_e2e
exec uv run python manage.py runserver 127.0.0.1:8010 --noreload
