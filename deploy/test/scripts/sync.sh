#!/usr/bin/env bash
# 从 stdin 接收 tar（只允许 docker-compose.yml 与 scripts/），校验后原子安装。
# 只由 deploy-wrapper.sh 的 `sync` 调用，不直接对外。
#
# 为什么连脚本一起同步：test-env 分支是这套环境的唯一真源。只同步 compose
# 的话，deploy.sh / wrapper 会在服务器上悄悄漂移——改了分支、线上却还是旧脚本，
# 而且没有任何地方会报错。
set -euo pipefail

ROOT="${TEST_ROOT:-/opt/club-test}"
STAGE="$(mktemp -d)"
ARCHIVE="$(mktemp)"
trap 'rm -rf "$STAGE" "$ARCHIVE"' EXIT

cat > "$ARCHIVE"
size=$(stat -c%s "$ARCHIVE")
[ "$size" -le 262144 ] || { echo "同步包过大：$size 字节" >&2; exit 1; }
[ "$size" -gt 0 ] || { echo "同步包为空" >&2; exit 1; }

# 白名单：逐项精确匹配，拒绝绝对路径 / .. / 额外文件（tar 里的路径就是字符串）。
LIST="$(tar -tf "$ARCHIVE")"
if printf '%s\n' "$LIST" | grep -qvE '^(docker-compose\.yml|scripts/(deploy\.sh|deploy-wrapper\.sh|sync\.sh))$'; then
  echo "同步包里有非法路径：" >&2
  printf '%s\n' "$LIST" | grep -vE '^(docker-compose\.yml|scripts/(deploy\.sh|deploy-wrapper\.sh|sync\.sh))$' >&2
  exit 1
fi
tar -xf "$ARCHIVE" -C "$STAGE" --no-same-owner

for required in docker-compose.yml scripts/deploy.sh scripts/deploy-wrapper.sh scripts/sync.sh; do
  [ -f "$STAGE/$required" ] || { echo "同步包缺少 $required" >&2; exit 1; }
done

# 用 /opt/club-test 作为项目目录：compose 校验时能读到同目录的 .env
docker compose --project-directory "$ROOT" -f "$STAGE/docker-compose.yml" config -q \
  || { echo "compose 校验失败，保留旧文件" >&2; exit 1; }

install_atomic() {
  local src="$1" dst="$2" mode="$3" tmp
  tmp="$(dirname "$dst")/.$(basename "$dst").new"
  cp "$src" "$tmp"
  chmod "$mode" "$tmp"
  mv -f "$tmp" "$dst"
}

install_atomic "$STAGE/docker-compose.yml" "$ROOT/docker-compose.yml" 644
for script in deploy.sh deploy-wrapper.sh sync.sh; do
  install_atomic "$STAGE/scripts/$script" "$ROOT/scripts/$script" 755
done

echo "已同步：compose $(stat -c%s "$ROOT/docker-compose.yml") 字节，3 个脚本"
