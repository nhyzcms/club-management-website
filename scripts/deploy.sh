#!/usr/bin/env bash
# deploy.sh — 容器化部署（生产侧唯一入口）。
#
# 由 CI 通过 SSH 强制命令调用，也可人工在服务器上执行。
#
#   deploy.sh stage  <tag>   拉镜像并记为待发布（不切换）
#   deploy.sh apply  <tag>   切换到这个 tag（迁移 + collectstatic + 重建容器 + 健康检查）
#   deploy.sh now    <tag>   stage + apply（忽略窗口）
#   deploy.sh tick           被 systemd timer 调用：有待发布且在窗口内就 apply
#   deploy.sh rollback       切回上一个 tag（不回滚数据库，见 --restore-db）
#   deploy.sh status         打印当前状态
#
# 全局参数：--dry-run 只打印将执行什么；--force 忽略「已经是这个 tag」跳过。
#
# 为什么切换要卡窗口：本站在上课时段也在用，重建容器有 5–15 秒的不可用窗口。
# 与旧的 Release 更新器保持同一个口径（默认 01:00–03:00 Asia/Shanghai）。
set -euo pipefail

APP_DIR="${CLUB_APP_DIR:-/opt/club}"
COMPOSE_FILE="$APP_DIR/docker-compose.yml"
ENV_FILE="$APP_DIR/.env"
RUN_DIR="$APP_DIR/run"
BACKUP_DIR="$APP_DIR/backups/db"
LOG_FILE="${CLUB_DEPLOY_LOG:-/var/log/club-deploy.log}"

IMAGE_REPO="${CLUB_IMAGE_REPO:-ghcr.io/nhyzcms/club-management-website}"
CONTAINER_NAME="club-app"
APPLIED_FILE="$RUN_DIR/applied-release"
PENDING_FILE="$RUN_DIR/pending-release"

KEEP_IMAGES="${CLUB_DEPLOY_KEEP_IMAGES:-3}"
KEEP_DUMPS="${CLUB_DEPLOY_KEEP_DUMPS:-5}"
HEALTH_TIMEOUT="${CLUB_DEPLOY_HEALTH_TIMEOUT:-90}"

DRY_RUN=0
FORCE=0
RESTORE_DB=""

# ── 参数解析 ────────────────────────────────────────────────────────────
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --force) FORCE=1 ;;
    --restore-db=*) RESTORE_DB="${arg#*=}" ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) ARGS+=("$arg") ;;
  esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}
CMD="${1:-status}"
shift || true

# ── 基础工具 ────────────────────────────────────────────────────────────
log() {
  local line
  line="$(printf '[%s] %s' "$(date -Is)" "$*")"
  printf '%s\n' "$line" >&2
  if [ -w "$(dirname "$LOG_FILE")" ] 2>/dev/null; then
    printf '%s\n' "$line" >>"$LOG_FILE" 2>/dev/null || true
  fi
}

die() { log "ERROR: $*"; exit 1; }

run() {
  if [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] $*"
  else
    log "+ $*"
    "$@"
  fi
}

env_get() {
  # 从 .env 里取一个键（不 source，避免键值里的空格/引号把当前 shell 打乱）
  local key="$1" default="${2:-}"
  if [ -f "$ENV_FILE" ]; then
    local value
    value="$(grep -E "^${key}=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    if [ -n "$value" ]; then printf '%s' "$value"; return; fi
  fi
  printf '%s' "$default"
}

tag_ok() {
  # 只接受我们自己的两种标签形态：sha-<40位小写hex> 或 sha-<前7~40位>
  [[ "$1" =~ ^sha-[0-9a-f]{7,40}$ ]]
}

# ── 状态读写 ────────────────────────────────────────────────────────────
read_applied() {
  # applied-release 是 key=value 文本；兼容旧更新器只写了一行 sha 的格式
  APPLIED_TAG=""; APPLIED_SHA=""; APPLIED_AT=""; APPLIED_PREV=""
  [ -f "$APPLIED_FILE" ] || return 0
  while IFS='=' read -r k v; do
    case "$k" in
      tag) APPLIED_TAG="$v" ;;
      sha) APPLIED_SHA="$v" ;;
      applied_at) APPLIED_AT="$v" ;;
      previous) APPLIED_PREV="$v" ;;
      *) [ -n "$k" ] && [ -z "$APPLIED_SHA" ] && [ ${#k} -ge 7 ] && APPLIED_SHA="$k" ;;
    esac
  done <"$APPLIED_FILE"
}

write_applied() {
  local tag="$1" prev="$2"
  {
    printf 'tag=%s\n' "$tag"
    printf 'sha=%s\n' "${tag#sha-}"
    printf 'applied_at=%s\n' "$(date -Is)"
    printf 'previous=%s\n' "$prev"
  } >"$APPLIED_FILE.tmp"
  mv "$APPLIED_FILE.tmp" "$APPLIED_FILE"
}

read_pending() {
  PENDING_TAG=""; PENDING_SHA=""; PENDING_AT=""
  [ -f "$PENDING_FILE" ] || return 0
  while IFS='=' read -r k v; do
    case "$k" in
      tag) PENDING_TAG="$v" ;;
      sha) PENDING_SHA="$v" ;;
      staged_at) PENDING_AT="$v" ;;
    esac
  done <"$PENDING_FILE"
}

write_pending() {
  local tag="$1"
  {
    printf 'tag=%s\n' "$tag"
    printf 'sha=%s\n' "${tag#sha-}"
    printf 'staged_at=%s\n' "$(date -Is)"
  } >"$PENDING_FILE.tmp"
  mv "$PENDING_FILE.tmp" "$PENDING_FILE"
}

clear_pending() { rm -f "$PENDING_FILE"; }

# ── 窗口判定 ────────────────────────────────────────────────────────────
in_window() {
  local tz start end now s e
  tz="$(env_get CLUB_DEPLOY_TZ Asia/Shanghai)"
  start="$(env_get CLUB_DEPLOY_WINDOW_START 01:00)"
  end="$(env_get CLUB_DEPLOY_WINDOW_END 03:00)"
  now="$(TZ="$tz" date +%H%M)"
  s="$((10#${start/:/}))"
  e="$((10#${end/:/}))"
  now="$((10#$now))"
  if [ "$s" -le "$e" ]; then
    [ "$now" -ge "$s" ] && [ "$now" -lt "$e" ]
  else
    # 跨零点窗口，例如 23:00–02:00
    [ "$now" -ge "$s" ] || [ "$now" -lt "$e" ]
  fi
}

# ── 镜像 ────────────────────────────────────────────────────────────────
image_ref() { printf '%s:%s' "$IMAGE_REPO" "$1"; }

image_present() {
  docker image inspect "$(image_ref "$1")" >/dev/null 2>&1
}

ensure_image() {
  local tag="$1"
  if image_present "$tag"; then
    log "镜像已存在：$(image_ref "$tag")"
    return 0
  fi
  run docker pull "$(image_ref "$tag")"
}

# ── 备份 ────────────────────────────────────────────────────────────────
db_dump() {
  local stamp file host port user pass name
  [ "$(env_get DB_ENGINE sqlite)" = "postgresql" ] || { log "非 PostgreSQL，跳过数据库备份"; return 0; }

  host="$(env_get DB_HOST 127.0.0.1)"
  # pgbouncer（6432）是 transaction 池模式，pg_dump 会失败——直连 PostgreSQL
  port="$(env_get CLUB_DEPLOY_DB_DUMP_PORT 5432)"
  user="$(env_get DB_USER club)"
  pass="$(env_get DB_PASSWORD "")"
  name="$(env_get DB_NAME club)"

  stamp="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP_DIR"
  file="$BACKUP_DIR/club-$stamp.sql.gz"

  if [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] pg_dump $name → $file"
    return 0
  fi

  log "备份数据库 → $file"
  if ! PGPASSWORD="$pass" pg_dump -h "$host" -p "$port" -U "$user" --no-owner --no-privileges "$name" | gzip -9 >"$file"; then
    rm -f "$file"
    die "数据库备份失败，中止部署（不带着无备份的状态迁移）"
  fi
  log "备份完成：$(du -h "$file" | cut -f1)"

  # 只留最近 KEEP_DUMPS 份
  ls -1t "$BACKUP_DIR"/club-*.sql.gz 2>/dev/null | tail -n +"$((KEEP_DUMPS + 1))" | while read -r old; do
    log "清理旧备份：$old"
    rm -f "$old"
  done
}

restore_db() {
  local file="$1"
  [ -f "$file" ] || die "备份文件不存在：$file"
  local host port user pass name
  host="$(env_get DB_HOST 127.0.0.1)"
  port="$(env_get CLUB_DEPLOY_DB_DUMP_PORT 5432)"
  user="$(env_get DB_USER club)"
  pass="$(env_get DB_PASSWORD "")"
  name="$(env_get DB_NAME club)"
  log "恢复数据库 $file → $name（这会覆盖现有数据）"
  run docker compose -f "$COMPOSE_FILE" stop app
  if [ "$DRY_RUN" = "0" ]; then
    gunzip -c "$file" | PGPASSWORD="$pass" psql -h "$host" -p "$port" -U "$user" -d "$name" -v ON_ERROR_STOP=1 >/dev/null
  fi
  log "数据库已恢复"
}

# ── 容器生命周期 ────────────────────────────────────────────────────────
one_shot() {
  # 用与运行时相同的镜像跑一次性命令（迁移 / collectstatic）
  local tag="$1"; shift
  local ref
  ref="$(image_ref "$tag")"
  run docker run --rm \
    --network host \
    --env-file "$ENV_FILE" \
    -v "$APP_DIR/.env:/app/.env:ro" \
    -v "$APP_DIR/data:/opt/club/data" \
    -v "$APP_DIR/staticfiles:/app/staticfiles" \
    -v "$RUN_DIR:/app/run" \
    "$ref" "$@"
}

compose_up() {
  local tag="$1"
  run env CLUB_IMAGE="$(image_ref "$tag")" docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate app
}

health_check() {
  local deadline status
  if [ "$DRY_RUN" = "1" ]; then log "[dry-run] 等待健康检查"; return 0; fi
  log "等待容器健康检查（最多 ${HEALTH_TIMEOUT}s）"
  deadline=$((SECONDS + HEALTH_TIMEOUT))
  while [ "$SECONDS" -lt "$deadline" ]; do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER_NAME" 2>/dev/null || echo missing)"
    case "$status" in
      healthy|running) log "容器状态：$status"; return 0 ;;
      unhealthy|exited|dead|missing) log "容器状态：$status"; return 1 ;;
    esac
    sleep 3
  done
  log "健康检查超时（最后状态：${status:-unknown}）"
  return 1
}

prune_images() {
  local keep="$1" tags
  # 只清理本仓库的 sha- 标签，别碰别的东西
  mapfile -t tags < <(docker image ls "$IMAGE_REPO" --format '{{.Tag}}' | grep -E '^sha-' || true)
  if [ "${#tags[@]}" -le "$KEEP_IMAGES" ]; then return 0; fi

  local -a sorted
  mapfile -t sorted < <(for t in "${tags[@]}"; do
      printf '%s %s\n' "$(docker image inspect "$(image_ref "$t")" --format '{{.Created}}' 2>/dev/null)" "$t"
    done | sort -r | awk '{print $2}')

  local i=0
  for t in "${sorted[@]}"; do
    i=$((i + 1))
    [ "$i" -le "$KEEP_IMAGES" ] && continue
    [ "$t" = "$keep" ] && continue
    log "清理旧镜像：$(image_ref "$t")"
    docker image rm "$(image_ref "$t")" >/dev/null 2>&1 || true
  done
}

# ── 动作 ────────────────────────────────────────────────────────────────
do_stage() {
  local tag="$1"
  tag_ok "$tag" || die "非法 tag：$tag（只接受 sha-<hex>）"
  read_applied
  if [ "$tag" = "$APPLIED_TAG" ] && [ "$FORCE" = "0" ]; then
    log "该 tag 已经在运行（$tag），stage 跳过"
    clear_pending
    return 0
  fi
  ensure_image "$tag"
  if [ "$DRY_RUN" = "0" ]; then
    write_pending "$tag"
    log "已登记待发布：$tag（当前运行 ${APPLIED_TAG:-未知}）"
  else
    log "[dry-run] 将登记待发布：$tag（当前运行 ${APPLIED_TAG:-未知}）"
  fi
}

do_apply() {
  local tag="$1"
  tag_ok "$tag" || die "非法 tag：$tag"

  read_applied
  if [ "$tag" = "$APPLIED_TAG" ] && [ "$FORCE" = "0" ]; then
    log "该 tag 已经在运行（$tag），apply 跳过"
    clear_pending
    return 0
  fi

  ensure_image "$tag"

  log "开始切换：${APPLIED_TAG:-无} → $tag"
  db_dump

  log "执行数据库迁移"
  one_shot "$tag" migrate

  log "收集静态文件（nginx 直出 /static/）"
  one_shot "$tag" collectstatic

  log "重建应用容器"
  compose_up "$tag"

  if ! health_check; then
    log "新版本健康检查失败，回滚到 ${APPLIED_TAG:-上一个镜像}"
    if [ -n "$APPLIED_TAG" ]; then compose_up "$APPLIED_TAG" || true; fi
    die "部署失败并已回滚，详见 $LOG_FILE"
  fi

  write_applied "$tag" "$APPLIED_TAG"
  clear_pending
  prune_images "$tag"
  log "✅ 部署完成：$tag（上一个：${APPLIED_TAG:-无}）"
}

do_tick() {
  read_pending
  if [ -z "$PENDING_TAG" ]; then
    return 0
  fi
  if in_window; then
    log "窗口内，应用待发布版本：$PENDING_TAG"
    do_apply "$PENDING_TAG"
  else
    log "窗口外，保留待发布版本：$PENDING_TAG（窗口 $(env_get CLUB_DEPLOY_WINDOW_START 01:00)–$(env_get CLUB_DEPLOY_WINDOW_END 03:00) $(env_get CLUB_DEPLOY_TZ Asia/Shanghai)）"
  fi
}

do_rollback() {
  read_applied
  local target="${1:-$APPLIED_PREV}"
  [ -n "$target" ] || die "没有可回滚的目标（applied-release 里没有 previous，也没有给参数）"
  log "回滚：${APPLIED_TAG:-无} → $target"
  if [ -n "$RESTORE_DB" ]; then restore_db "$RESTORE_DB"; fi
  log "注意：数据库迁移不会自动回退。schema 已前移时，仅回退代码可能需要配 --restore-db=<备份>"
  do_apply "$target"
}

do_status() {
  read_applied; read_pending
  printf '运行中:   %s\n' "${APPLIED_TAG:-（无记录）}"
  printf '提交:     %s\n' "${APPLIED_SHA:-（无记录）}"
  printf '应用时间: %s\n' "${APPLIED_AT:-（无记录）}"
  printf '上一版本: %s\n' "${APPLIED_PREV:-（无记录）}"
  printf '待发布:   %s\n' "${PENDING_TAG:-（无）}"
  if in_window; then printf '窗口:     当前在窗口内\n'; else printf '窗口:     当前在窗口外\n'; fi
  printf '容器:     %s\n' "$(docker inspect -f '{{.State.Status}} / {{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' "$CONTAINER_NAME" 2>/dev/null || echo '不存在')"
  printf '镜像:     %s\n' "$(docker inspect -f '{{.Config.Image}}' "$CONTAINER_NAME" 2>/dev/null || echo '-')"
}

# ── 主分派 ──────────────────────────────────────────────────────────────
command -v docker >/dev/null || die "未安装 docker"
[ -f "$COMPOSE_FILE" ] || die "缺少 $COMPOSE_FILE（先跑 scripts/install-docker-host.sh）"

case "$CMD" in
  stage)    do_stage "${1:?stage 需要 tag}" ;;
  apply)    do_apply "${1:?apply 需要 tag}" ;;
  now)      do_stage "${1:?now 需要 tag}" && do_apply "${1}" ;;
  tick)     do_tick ;;
  rollback) do_rollback "${1:-}" ;;
  status)   do_status ;;
  *)        die "未知命令：$CMD（stage / apply / now / tick / rollback / status）" ;;
esac
