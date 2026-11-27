#!/usr/bin/env bash
# test 环境部署脚本（在 /opt/club-test 下以 clubdeploy 身份运行）。
#
#   deploy.sh deploy <tag>   # 拉镜像 → migrate → collectstatic → 起容器 → 探活（失败自动回滚）
#   deploy.sh status         # 当前镜像 / 容器状态 / 探活
#   deploy.sh logs           # 跟 web 日志
#   deploy.sh down           # 停栈（数据保留）
#
# tag 由 CI 传入（test-<sha12>），也接受 sha-<sha> / vX.Y.Z 便于人工验证。
# 唯一真源是 /opt/club-test/.last-good：部署成功才写，回滚读它。
set -euo pipefail

ROOT="${TEST_ROOT:-/opt/club-test}"
COMPOSE="$ROOT/docker-compose.yml"
ENV_FILE="$ROOT/.env"
LAST_GOOD="$ROOT/.last-good"
IMAGE_REPO="${IMAGE_REPO:-ghcr.io/nhyzcms/club-management-website}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/healthz/}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { printf '[%s] ❌ %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }

[ -f "$COMPOSE" ] || die "缺少 $COMPOSE（应由 CI 的 sync 步骤写入）"
[ -f "$ENV_FILE" ] || die "缺少 $ENV_FILE（先按 README 生成）"

compose() { docker compose -f "$COMPOSE" "$@"; }

health() { curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; }

wait_health() {
  local waited=0
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    if health; then
      log "探活通过（${waited}s）"
      return 0
    fi
    sleep 3
    waited=$((waited + 3))
  done
  return 1
}

cmd_deploy() {
  local tag="${1:?用法: deploy.sh deploy <tag>}"
  # 只接受可预期的三类 tag，避免把任意字符串拼进镜像引用。
  [[ "$tag" =~ ^(test|sha)-[0-9a-f]{7,40}$ || "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || die "非法镜像 tag：$tag"

  local prev=""
  if [ -f "$LAST_GOOD" ]; then prev="$(cat "$LAST_GOOD")"; fi

  export CLUB_TEST_IMAGE="$IMAGE_REPO:$tag"
  log "部署 $CLUB_TEST_IMAGE（上一版：${prev:-无}）"

  log "拉取镜像（GHCR 可能较慢，最长等 15 分钟）"
  # 注意：compose 是 shell 函数，timeout 不能直接执行函数——必须写全 docker compose。
  timeout 900 docker compose -f "$COMPOSE" pull web

  log "数据库迁移"
  compose run --rm web migrate

  log "收集静态文件"
  compose run --rm web collectstatic --noinput

  log "启动容器"
  compose up -d --remove-orphans

  if wait_health; then
    printf '%s\n' "$tag" > "$LAST_GOOD"
    log "✅ 部署成功：$tag"
    log "   入口：http://<公网 IP>:8080/（HTTP Basic）"
    return 0
  fi

  log "❌ 健康检查失败（${HEALTH_TIMEOUT}s），web 日志尾部："
  compose logs --tail 80 web || true
  if [ -n "$prev" ] && [ "$prev" != "$tag" ]; then
    log "尝试回滚到 $prev"
    export CLUB_TEST_IMAGE="$IMAGE_REPO:$prev"
    compose up -d --remove-orphans || true
  fi
  die "部署失败"
}

cmd_status() {
  echo "=== 当前部署 ==="
  echo "  last-good: $(cat "$LAST_GOOD" 2>/dev/null || echo '（尚无成功部署记录）')"
  echo "=== 容器 ==="
  compose ps || true
  echo "=== 探活 ==="
  if health; then echo "  $HEALTH_URL → 200"; else echo "  $HEALTH_URL → 不可达"; fi
}

cmd_logs() { compose logs -f --tail 100 web; }
cmd_down() { compose down --remove-orphans; log "已停止（数据保留）"; }

case "${1:-status}" in
  deploy) shift; cmd_deploy "$@" ;;
  status) shift; cmd_status ;;
  logs)   shift; cmd_logs ;;
  down)   shift; cmd_down ;;
  *) echo "用法: $0 {deploy <tag>|status|logs|down}" >&2; exit 2 ;;
esac
