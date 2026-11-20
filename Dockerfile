# syntax=docker/dockerfile:1.7
#
# 单镜像、多阶段构建。CI 构建后推 ghcr.io，生产只拉不构建
# （生产机 1.87 GB 内存，跑 npm + webpack + uv 会 OOM）。
#
# 运行时目录约定与裸机安装完全一致：
#   /app            代码 + .venv（start.sh 原样复用，不另起一套启动逻辑）
#   /app/frontend/dist  前端产物（镜像内，Django 直接托管）
#   /app/staticfiles    collectstatic 输出（nginx 直出 → 必须 bind mount 到宿主机）
#   /opt/club/data      media / private_media / ip2region 库（宿主持久卷，路径与 .env 一致）
#   /app/run/gunicorn.sock   nginx 反代目标（bind mount 到 /opt/club/run）

ARG PYTHON_VERSION=3.14
ARG NODE_VERSION=22
ARG UV_VERSION=0.11.28

# ── 1. 前端产物 ────────────────────────────────────────────────────────
FROM node:${NODE_VERSION}-bookworm-slim AS frontend
WORKDIR /build/frontend

# 先只拷 manifest：依赖层可缓存，改业务代码不必重装 node_modules
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# npm run build 末尾自带 assert-live2d-dist / assert-surveyjs-dist 两个构建缝检查，
# 任一资产缺失即整步失败——不要在 Dockerfile 里绕过它们。
RUN npm run build && test -f dist/surveyjs/survey.core.min.js

# ── 2. Python 依赖 ─────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS deps
ARG UV_VERSION
COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# ── 3. 源码修剪 ────────────────────────────────────────────────────────
# 构建期才需要的东西（node_modules / src / vendor / .git）必须在这一层删掉。
# 直接在 runtime 里 COPY 再 rm 没用：rm 只产生 whiteout，被删的字节仍留在
# 前面那层的 blob 里，镜像照样大几百 MB。COPY --from 拷的是层内当前状态。
FROM python:${PYTHON_VERSION}-slim AS source
WORKDIR /src
COPY . ./
RUN rm -rf \
        frontend/node_modules \
        frontend/dist \
        frontend/src \
        frontend/vendor \
        frontend/e2e \
        frontend/playwright-report \
        frontend/test-results \
        .git .github docs .venv \
        data media private_media staticfiles backups run tmp \
    && find . -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && find . -name '*.py[cod]' -delete

# ── 4. 运行时 ──────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    DJANGO_SETTINGS_MODULE=config.settings \
    PATH=/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

WORKDIR /app

COPY --from=deps /app/.venv /app/.venv
COPY --from=source /src /app
COPY --from=frontend /build/frontend/dist /app/frontend/dist
COPY --from=source /src/docker/entrypoint.sh /usr/local/bin/club-entrypoint
RUN chmod +x /usr/local/bin/club-entrypoint /app/start.sh

# HEALTHCHECK 探的是 nginx 真正反代的那个 unix socket：socket 能连上，
# 说明 gunicorn 已经接管请求，比探 TCP 端口更接近「站点可用」。
# 注意：HEALTHCHECK 不支持 heredoc（只有 RUN 支持），必须写成单行。
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(3); sys.exit(s.connect_ex('/app/run/gunicorn.sock'))"

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/club-entrypoint"]
CMD ["web"]
