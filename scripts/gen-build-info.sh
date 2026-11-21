#!/usr/bin/env bash
# 生成 build_info.json —— 版本号的唯一写入口。
#
# 由 .github/workflows/image.yml 在 docker build 之前调用；本地也能跑，
# 只是没有 CI 环境变量时 commit/ref 之类会从 git 现读，读不到就留空。
#
# 判定规则（都不依赖「人记得改」）：
#   ref 是 tag                → channel=release，version=tag 去掉 v
#   提交把 pyproject 的 version 改了 → channel=release（这就是发布提交本身）
#   其余                      → channel=dev，version=<base>-dev.<n>.g<sha7>
#
# 第二条是为了消除竞态：main 上构建镜像时，打 tag 的 job 还在并发跑。
# 等 tag 出现再决定版本，会让同一份代码时而 release 时而 dev。
# 「版本号变了」这件事在提交里就是确定的。
set -euo pipefail

OUT="${1:-build_info.json}"
cd "$(dirname "$0")/.."

BASE=$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' pyproject.toml | head -1)
[ -n "$BASE" ] || { echo "gen-build-info: pyproject.toml 里读不到 version" >&2; exit 1; }

SHA=$(git rev-parse HEAD 2>/dev/null || true)
SHORT="${SHA:0:7}"
REF_TYPE="${GITHUB_REF_TYPE:-}"
REF_NAME="${GITHUB_REF_NAME:-}"
[ -n "$REF_NAME" ] || REF_NAME=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)

CHANNEL="dev"
TAG=""

if [ "$REF_TYPE" = "tag" ]; then
  CHANNEL="release"
  TAG="$REF_NAME"
  VERSION="${REF_NAME#v}"
elif [ -n "$SHA" ]; then
  # --verify --quiet：浅克隆里 HEAD^ 解析不出来时，普通 rev-parse 会把参数
  # 原样打到 stdout（"<sha>^"），`[ -n "$PARENT" ]` 因此为真，后面 git show 真的
  # 失败，pipefail + set -e 直接以 128 退出。CI 的浅克隆就是这么炸的。
  PARENT=$(git rev-parse --verify --quiet "${SHA}^" 2>/dev/null || true)
  if [ -n "$PARENT" ]; then
    PREV=$(git show "${PARENT}:pyproject.toml" 2>/dev/null \
      | sed -n 's/^version *= *"\([^"]*\)".*/\1/p' | head -1 || true)
    if [ -n "$PREV" ] && [ "$PREV" != "$BASE" ]; then
      CHANNEL="release"
      VERSION="$BASE"
      echo "gen-build-info: 检测到版本号 ${PREV} → ${BASE}，按发布提交处理" >&2
    fi
  fi
fi

# 还没定版本（dev 分支）时，找一个基准 tag 和距它的提交数。
# 只认 v* —— 仓库里还留着 266 个历史的 club-<sha> tag，不加 --match 会抓到它们
if [ -z "${VERSION:-}" ]; then
  TAG=$(git describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || true)
  if [ -n "$TAG" ]; then
    N=$(git rev-list --count "${TAG}..HEAD" 2>/dev/null || echo 0)
  else
    N=$(git rev-list --count HEAD 2>/dev/null || echo 0)
  fi
  if [ -z "$SHA" ]; then
    VERSION="${BASE}-dev"
  else
    VERSION="${BASE}-dev.${N}.g${SHORT}"
  fi
else
  TAG=$(git describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || true)
  N=$(git rev-list --count "${TAG}..HEAD" 2>/dev/null || echo 0)
fi

# tag 字段要么是 "v1.2.3" 要么是 null，不能是空字符串以外的半成品
if [ -n "$TAG" ]; then TAG_JSON="\"${TAG}\""; else TAG_JSON="null"; fi
[ -n "$SHA" ] || SHA=""

cat > "$OUT" <<EOF
{
  "version": "${VERSION}",
  "base_version": "${BASE}",
  "channel": "${CHANNEL}",
  "tag": ${TAG_JSON},
  "commits_since_tag": ${N:-0},
  "commit": "${SHA}",
  "commit_short": "${SHORT}",
  "ref": "${REF_NAME}",
  "ref_type": "${REF_TYPE:-branch}",
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "built_by": "${GITHUB_ACTOR:-local}",
  "run_id": "${GITHUB_RUN_ID:-}"
}
EOF

echo "gen-build-info: ${VERSION} (${CHANNEL}) → ${OUT}" >&2
