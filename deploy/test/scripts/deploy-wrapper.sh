#!/usr/bin/env bash
# SSH 强制命令入口（authorized_keys 里 restrict,command= 指向这里）。
#
# 这条 key 只给 test 环境用，能力就两个：
#   sync            ← 从 stdin 覆盖 docker-compose.yml（CI 推送）
#   deploy <tag>    ← 部署一个镜像 tag
# 除此之外一律拒绝；生产 deploy key 是另一把、另一套 wrapper。
set -euo pipefail

cmd="${SSH_ORIGINAL_COMMAND:-status}"
case "$cmd" in
  sync)       exec /opt/club-test/scripts/sync-compose.sh ;;
  "deploy "*) exec /opt/club-test/scripts/deploy.sh deploy "${cmd#deploy }" ;;
  status)     exec /opt/club-test/scripts/deploy.sh status ;;
  *)
    echo "denied: 只允许 sync / deploy <tag> / status" >&2
    exit 1
    ;;
esac
