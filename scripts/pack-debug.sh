#!/usr/bin/env bash
# 打包「调试包」：某个发布版本的完整源码 + test 环境编排（应用 + PostgreSQL + Redis）。
#
# 用途：Release 页面上除了源码包，再给测试 / 调试的人一个能直接跑起来的包。
# 解压后 `docker compose -f deploy/test/docker-compose.debug.yml up -d --build`
# 即可得到一份带 DEBUG 错误页与 HTTP Basic 登录的完整站点。
#
# 用法：scripts/pack-debug.sh <version> <output-dir>
#   version 不带 v，例如 1.2.3
#   test 环境相关文件来自 test-env 分支（test 服务器由那条长期分支维护）
#
# 依赖：在 git 工作区内运行，且 origin 上有 v<version> tag 与 test-env 分支。
set -euo pipefail

VERSION="${1:?用法: pack-debug.sh <version> <output-dir>}"
OUT="${2:?用法: pack-debug.sh <version> <output-dir>}"
TEST_BRANCH="${TEST_BRANCH:-test-env}"
TAG="v${VERSION}"
NAME="club-${VERSION}-debug"

die() { echo "❌ $*" >&2; exit 1; }

git rev-parse --verify --quiet "$TAG" >/dev/null || die "找不到 tag $TAG"
git fetch -q origin "$TEST_BRANCH" || die "拉不到分支 $TEST_BRANCH"

mkdir -p "$OUT/$NAME"

echo "== 写入 $TAG 的源码 =="
git archive "$TAG" | tar -x -C "$OUT/$NAME"
# 仓库里被跟踪的运行期数据不进调试包：media 是线上上传物（本站 ~66MB），
# staticfiles / data / db 是构建或运行产物，留着只会把包撑大。
rm -rf "$OUT/$NAME/media" "$OUT/$NAME/private_media" "$OUT/$NAME/data" \
       "$OUT/$NAME/staticfiles" "$OUT/$NAME/backups" "$OUT/$NAME/run" \
       "$OUT/$NAME/db.sqlite3" "$OUT/$NAME/pgdata"

echo "== 从 $TEST_BRANCH 取 test 环境文件 =="
mkdir -p "$OUT/$NAME/deploy/test"
for file in docker-compose.debug.yml .env.example README.md; do
  git show "origin/$TEST_BRANCH:deploy/test/$file" > "$OUT/$NAME/deploy/test/$file" \
    || die "$TEST_BRANCH 缺少 deploy/test/$file"
done

cat > "$OUT/$NAME/README-DEBUG.md" <<EOF
# 调试包 v${VERSION}

${TAG} 的完整源码，外加一套「开箱即用」的 test 环境编排：Django（DEBUG=1）
+ PostgreSQL 17 + Redis，只暴露一个端口 8080，整站套 HTTP Basic 登录。

## 启动

\`\`\`bash
cp deploy/test/.env.example .env    # 至少改 SECRET_KEY / 两个 Basic 凭据
docker compose -f deploy/test/docker-compose.debug.yml up -d --build
\`\`\`

首次构建要联网装 npm / Python 依赖，约 3–5 分钟。启动后打开
<http://127.0.0.1:8080/>，浏览器会弹 Basic 登录框（账号密码在 \`.env\` 里）。

数据落在仓库根目录的 \`data/\`、\`staticfiles/\`、\`pgdata/\`，不会碰你机器上
其他站点；清空重来就是删掉这三个目录再 \`down\`。

## 注意

- 这是**调试**配置：\`DJANGO_DEBUG=1\` 会把 traceback、局部变量与 settings
  片段打进错误页。只给自己 / 信得过的人访问，别当生产用。
- HTTP Basic 走明文 HTTP，凭据不加密；仅限内网 / 本机，或自己再套一层 HTTPS。
- 完整说明（含 test 服务器运维、冲突处理）见 \`deploy/test/README.md\`。
EOF

echo "== 压缩 =="
tar -C "$OUT" -czf "$OUT/$NAME.tar.gz" "$NAME"
( cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256" )

echo "✅ $OUT/$NAME.tar.gz"
ls -lh "$OUT/$NAME.tar.gz"
