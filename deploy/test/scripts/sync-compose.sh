#!/usr/bin/env bash
# 从 stdin 接收 docker-compose.yml，校验后原子替换 /opt/club-test/docker-compose.yml。
# 只由 deploy-wrapper.sh 的 `sync` 调用，不直接对外。
set -euo pipefail

ROOT="${TEST_ROOT:-/opt/club-test}"
TARGET="$ROOT/docker-compose.yml"
TMP="$(mktemp "$ROOT/.docker-compose.yml.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

cat > "$TMP"

size=$(stat -c%s "$TMP")
[ "$size" -le 65536 ] || { echo "compose 文件过大：$size 字节" >&2; exit 1; }

# 语法 + 变量插值校验（.env 与 compose 同目录，compose 会自动读取）
docker compose -f "$TMP" config -q || { echo "compose 校验失败，保留旧文件" >&2; exit 1; }

mv "$TMP" "$TARGET"
trap - EXIT
echo "compose 已更新：$size 字节"
