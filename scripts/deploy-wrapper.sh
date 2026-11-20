#!/usr/bin/env bash
# deploy-wrapper.sh — CI 的 SSH 强制命令入口。
#
# authorized_keys 里配 `command="/opt/club/scripts/deploy-wrapper.sh"`，
# 因此这条密钥无论带什么参数，都只能落到这里。命令从 SSH_ORIGINAL_COMMAND 读，
# 严格白名单后转交 deploy.sh —— 密钥泄露也只能「拉镜像 / 切换版本」，
# 拿不到交互式 shell，也不能执行任意命令。
set -euo pipefail

ORIG="${SSH_ORIGINAL_COMMAND:-}"
DEPLOY=/opt/club/scripts/deploy.sh

if [ -z "$ORIG" ]; then
  echo "denied: 需要显式命令（stage <tag> / tick / status）" >&2
  exit 2
fi

# 只按空白切分，不做任何 shell 求值；tag 的合法性由 deploy.sh 再校验一次
read -r -a argv <<<"$ORIG"

case "${argv[0]:-}" in
  stage)
    [ "${#argv[@]}" -eq 2 ] || { echo "denied: stage 只接受一个 tag 参数" >&2; exit 2; }
    exec "$DEPLOY" stage "${argv[1]}"
    ;;
  tick)
    [ "${#argv[@]}" -eq 1 ] || { echo "denied: tick 不接受参数" >&2; exit 2; }
    exec "$DEPLOY" tick
    ;;
  status)
    [ "${#argv[@]}" -eq 1 ] || { echo "denied: status 不接受参数" >&2; exit 2; }
    exec "$DEPLOY" status
    ;;
  *)
    echo "denied: 不允许的命令 '${argv[0]}'" >&2
    exit 2
    ;;
esac
