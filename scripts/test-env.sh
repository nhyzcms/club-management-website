#!/usr/bin/env bash
# test-env.sh — 起停「预演环境」（容器化，与生产数据面隔离）
#
# 设计意图：用**环境**隔离代替**分支**隔离。
# 跑的是 develop（或任意 sha）的镜像，但数据、静态、端口全部独立，
# 停掉或清空都碰不到生产。
#
#   sudo scripts/test-env.sh init            # 一次性：建目录 / 生成 .env / 建库 / 装 nginx
#   sudo scripts/test-env.sh up sha-abc1234  # 拉起某个镜像
#   sudo scripts/test-env.sh status
#   sudo scripts/test-env.sh logs
#   sudo scripts/test-env.sh down            # 停掉（保留数据）
#   sudo scripts/test-env.sh reset --yes     # 停掉并清空数据
#
# 访问方式（不需要开安全组 / 域名 / 证书）：
#   ssh -N -L 8080:127.0.0.1:8080 nhyz-prod
#   浏览器 http://127.0.0.1:8080/
set -euo pipefail

TEST_ROOT="${TEST_ROOT:-/opt/club-test}"
PROD_ROOT="${PROD_ROOT:-/opt/club}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_FILE="$TEST_ROOT/test-compose.yml"
ENV_FILE="$TEST_ROOT/.env"
NGINX_CONF="/etc/nginx/conf.d/club-test.conf"
APP_PORT="${APP_PORT:-18080}"
HTTP_PORT="${HTTP_PORT:-8080}"
IMAGE_REPO="${IMAGE_REPO:-ghcr.io/nhyzcms/club-management-website}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { printf '[%s] ❌ %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "需要 root：sudo $0 $*"; }

compose() {
  env CLUB_IMAGE="${CLUB_IMAGE:-}" docker compose -f "$COMPOSE_FILE" "$@"
}

# 生产 .env 派生 test .env：只改必须改的，其余原样继承。
gen_env() {
  [ -f "$PROD_ROOT/.env" ] || die "找不到 $PROD_ROOT/.env，无法派生 test 配置"
  log "从 $PROD_ROOT/.env 派生 $ENV_FILE"

  python3 - "$PROD_ROOT/.env" "$ENV_FILE" <<'PY'
import secrets, sys

src, dst = sys.argv[1], sys.argv[2]
secret = secrets.token_urlsafe(64)

# 必须覆盖的键：隔离 + 调试
overrides = {
    "SECRET_KEY": secret,                      # 独立密钥：两个环境不能共用签名
    "DJANGO_DEBUG": "1",                       # 预演环境要看得见报错
    "ALLOWED_HOSTS": "127.0.0.1,localhost",
    "FRONTEND_URL": "http://127.0.0.1:8080",
    "DB_NAME": "club_test",                    # 独立库
    "REDIS_URL": "redis://127.0.0.1:6379/1",   # 同实例不同 db：缓存与频道层不串
    "GUNICORN_WORKERS": "2",
    "CLUB_UPDATER_PROXY": "",                  # 更新器已弃用
    "UPDATE_GITHUB_TOKEN": "",                 # test 不碰 GitHub
    "UPDATE_GITHUB_REPO": "",
}

out, seen = [], set()
for line in open(src, encoding="utf-8"):
    raw = line.rstrip("\n")
    if not raw or raw.lstrip().startswith("#") or "=" not in raw:
        out.append(raw)
        continue
    key = raw.split("=", 1)[0].strip()
    if key in overrides:
        out.append(f"{key}={overrides[key]}")
        seen.add(key)
    else:
        out.append(raw)

for key, val in overrides.items():
    if key not in seen:
        out.append(f"{key}={val}")

open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"  覆盖 {len(seen)} 个已有键，补写 {len(overrides) - len(seen)} 个缺失键")
PY

  chmod 640 "$ENV_FILE"
  chown root:root "$ENV_FILE"
}

ensure_db() {
  local db="club_test"
  if ! command -v psql >/dev/null 2>&1; then
    log "⚠️  本机没有 psql，跳过建库；请手工创建 $db"
    return 0
  fi
  if sudo -n -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" 2>/dev/null | grep -q 1; then
    log "数据库 $db 已存在"
    return 0
  fi
  local owner
  owner="$(grep -E '^DB_USER=' "$ENV_FILE" | cut -d= -f2- | tr -d "\"'")"
  owner="${owner:-club}"
  log "创建数据库 $db（owner=$owner）"
  sudo -n -u postgres createdb -O "$owner" "$db" || die "建库失败（需要 postgres 超级用户权限）"
}

cmd_init() {
  need_root init
  mkdir -p "$TEST_ROOT/data" "$TEST_ROOT/staticfiles" "$TEST_ROOT/run"
  chmod 775 "$TEST_ROOT/run"

  [ -f "$ENV_FILE" ] || gen_env
  [ -f "$ENV_FILE" ] || die "生成 $ENV_FILE 失败"
  # 已存在的 .env 不覆盖，但要保证 DEBUG/DB 名是对的（防止有人从生产拷过来）
  grep -q '^DB_NAME=club_test$' "$ENV_FILE" || die "$ENV_FILE 里 DB_NAME 不是 club_test，请检查"

  install -m 644 "$REPO_ROOT/deploy/test-compose.yml" "$COMPOSE_FILE"
  install -m 644 "$REPO_ROOT/deploy/nginx-club-test.conf" "$NGINX_CONF"

  ensure_db

  if grep -q 'map \$http_upgrade \$connection_upgrade' /etc/nginx/conf.d/club.conf 2>/dev/null; then
    log "nginx map 已由 club.conf 提供"
  else
    log "⚠️  club.conf 里没有 \$connection_upgrade 的 map，test 站点的 WebSocket 会 400"
  fi

  nginx -t || die "nginx 配置检查失败"
  systemctl reload nginx
  log "✅ init 完成。下一步：sudo $0 up sha-<sha>"
}

cmd_up() {
  need_root up
  local tag="${1:?用法: test-env.sh up <tag，如 sha-abc1234>}"
  export CLUB_IMAGE="$IMAGE_REPO:$tag"

  [ -f "$COMPOSE_FILE" ] || die "还没 init：先跑 sudo $0 init"

  log "拉取镜像 $CLUB_IMAGE"
  compose pull

  log "迁移数据库"
  docker run --rm --network host --env-file "$ENV_FILE" \
    -e CLUB_SPAWN_UPDATER=0 \
    -v "$ENV_FILE:/app/.env:ro" \
    -v "$TEST_ROOT/data:/opt/club/data" \
    -v "$TEST_ROOT/staticfiles:/app/staticfiles" \
    -v "$TEST_ROOT/run:/app/run" \
    "$CLUB_IMAGE" migrate

  log "收集静态文件"
  docker run --rm --network host --env-file "$ENV_FILE" \
    -e CLUB_SPAWN_UPDATER=0 \
    -v "$ENV_FILE:/app/.env:ro" \
    -v "$TEST_ROOT/data:/opt/club/data" \
    -v "$TEST_ROOT/staticfiles:/app/staticfiles" \
    -v "$TEST_ROOT/run:/app/run" \
    "$CLUB_IMAGE" collectstatic

  log "启动容器"
  compose up -d --force-recreate

  log "等待健康（最多 ${HEALTH_TIMEOUT}s）"
  local i=0
  while [ "$i" -lt "$HEALTH_TIMEOUT" ]; do
    if curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1:$HTTP_PORT/site-policy/" 2>/dev/null; then
      log "✅ test 环境就绪：http://127.0.0.1:$HTTP_PORT/"
      log "   隧道：ssh -N -L $HTTP_PORT:127.0.0.1:$HTTP_PORT <本机>"
      return 0
    fi
    sleep 3; i=$((i + 3))
  done
  log "❌ 健康检查超时，看日志：sudo $0 logs"
  exit 1
}

cmd_down() {
  need_root down
  [ -f "$COMPOSE_FILE" ] || die "还没 init"
  compose down --remove-orphans
  log "test 环境已停止（数据保留在 $TEST_ROOT/data）"
}

cmd_reset() {
  need_root reset
  [ "${1:-}" = "--yes" ] || die "会清空 $TEST_ROOT/data，确认请加 --yes"
  compose down --remove-orphans 2>/dev/null || true
  rm -rf "$TEST_ROOT/data" "$TEST_ROOT/staticfiles"
  mkdir -p "$TEST_ROOT/data" "$TEST_ROOT/staticfiles"
  log "数据已清空"
}

cmd_status() {
  echo "=== 容器 ==="
  docker ps -a --filter name=club-test-app --format '  {{.Names}} | {{.Status}} | {{.Image}}' || true
  echo "=== 镜像 ==="
  docker image ls "$IMAGE_REPO" --format '  {{.Tag}} {{.Size}}' | head -5
  echo "=== 端口 ==="
  ss -lntp 2>/dev/null | grep -E ":($APP_PORT|$HTTP_PORT)" || echo "  （未监听）"
  echo "=== 探活 ==="
  curl -fsS -o /dev/null -w "  http://127.0.0.1:$HTTP_PORT/ → %{http_code}\n" \
    --max-time 5 "http://127.0.0.1:$HTTP_PORT/" 2>/dev/null || echo "  不可达"
}

cmd_logs() {
  docker logs -f --tail 100 club-test-app
}

case "${1:-status}" in
  init)    shift; cmd_init "$@" ;;
  up)      shift; cmd_up "$@" ;;
  down)    shift; cmd_down "$@" ;;
  reset)   shift; cmd_reset "$@" ;;
  status)  shift; cmd_status "$@" ;;
  logs)    shift; cmd_logs "$@" ;;
  *)       echo "用法: $0 {init|up <tag>|down|reset --yes|status|logs}"; exit 2 ;;
esac
