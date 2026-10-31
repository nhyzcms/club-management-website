#!/usr/bin/env bash
# install.sh — 裸机安装 / 就地部署（Nginx + Gunicorn + SQLite + systemd）。
#
# 不绑死 Debian/Ubuntu：自动识别 apt / dnf / yum；Nginx 同时支持
# sites-available（Debian）与 conf.d（RHEL / 阿里云 Linux / Anolis 等）。
#
# 两种入口：
#   1) 已有源码树（git clone 或解压过的 release）：sudo ./scripts/install.sh
#   2) 独立安装（无需先 clone）：把本脚本单独拿来跑，会拉最新 GitHub Release。
#        curl -fsSL https://github.com/nhyzcms/club-management-website/releases/latest/download/install.sh -o install.sh
#        sudo bash install.sh
#      管道安装请加 -y（否则 read 会把脚本自身当输入）。私有仓库加 GITHUB_TOKEN。
#
# 安装时写入：SECRET_KEY（空则生成）、FRONTEND_URL、ALLOWED_HOSTS、DJANGO_DEBUG=0，
# 并创建第一个超级用户。已有非空值 / 已有超管则跳过。
#
# Release 包已含 frontend/dist，独立安装不需要 Node。只有就地构建源码树才装 Node。
#
# 用法：
#   sudo ./scripts/install.sh
#   sudo ./scripts/install.sh --skip-deps
#   sudo ./scripts/install.sh -y
#   sudo ./scripts/install.sh --from-release              # 强制拉最新 release
#   sudo ./scripts/install.sh --from-release club-<sha>   # 指定 tag / sha
#   sudo APP_DIR=/opt/club APP_USER=club SERVER_NAME=club.example.com \
#        FRONTEND_URL=http://club.example.com \
#        SUPERUSER_USERNAME=admin SUPERUSER_PASSWORD='...' ./scripts/install.sh -y
set -euo pipefail

GITHUB_REPO="${GITHUB_REPO:-${UPDATE_GITHUB_REPO:-nhyzcms/club-management-website}}"
GITHUB_TOKEN="${GITHUB_TOKEN:-${UPDATE_GITHUB_TOKEN:-}}"
SERVICE_NAME="${SERVICE_NAME:-club}"
SERVER_NAME="${SERVER_NAME:-_}"
SYSTEMCTL="$(command -v systemctl || echo /usr/bin/systemctl)"

SKIP_DEPS=0
ASSUME_YES=0
FROM_RELEASE=0
RELEASE_REF=""

usage() {
  sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
}

SUPERUSER_USERNAME="${SUPERUSER_USERNAME:-${DJANGO_SUPERUSER_USERNAME:-admin}}"
SUPERUSER_EMAIL="${SUPERUSER_EMAIL:-${DJANGO_SUPERUSER_EMAIL:-admin@localhost}}"
SUPERUSER_PASSWORD="${SUPERUSER_PASSWORD:-${DJANGO_SUPERUSER_PASSWORD:-}}"
FRONTEND_URL="${FRONTEND_URL:-}"
GENERATED_ADMIN_PASSWORD=""

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-deps) SKIP_DEPS=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    --from-release)
      FROM_RELEASE=1
      if [ "${2:-}" ] && [ "${2#-}" = "$2" ]; then
        RELEASE_REF="$2"
        shift
      fi
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1（可用：--skip-deps / -y / --from-release [tag]）" >&2
      exit 2
      ;;
  esac
  shift
done

INTERACTIVE=0
if [ "$ASSUME_YES" = 0 ] && [ -t 0 ]; then
  INTERACTIVE=1
fi

[ "$(id -u)" = 0 ] || { echo "须以 root 运行：sudo $0" >&2; exit 1; }

script_dir() {
  local src="${BASH_SOURCE[0]:-}"
  if [ -n "$src" ] && [ -f "$src" ]; then
    (cd "$(dirname "$src")" && pwd)
  else
    echo ""
  fi
}

SCRIPT_DIR="$(script_dir)"
DIR=""
CANDIDATES=()
[ -n "${APP_DIR:-}" ] && CANDIDATES+=("$APP_DIR")
[ -n "${INSTALL_DIR:-}" ] && CANDIDATES+=("$INSTALL_DIR")
if [ -n "$SCRIPT_DIR" ]; then
  CANDIDATES+=("$SCRIPT_DIR")
  CANDIDATES+=("$(dirname "$SCRIPT_DIR")")
fi
if [ "$FROM_RELEASE" = 0 ]; then
  for candidate in "${CANDIDATES[@]}"; do
    if [ -f "$candidate/manage.py" ]; then
      DIR="$(cd "$candidate" && pwd)"
      break
    fi
  done
fi
NEED_DOWNLOAD=0
if [ -z "$DIR" ]; then
  DIR="${APP_DIR:-${INSTALL_DIR:-/opt/club}}"
  NEED_DOWNLOAD=1
fi

PKG=""
detect_pkg() {
  if command -v apt-get >/dev/null 2>&1; then
    PKG=apt
  elif command -v dnf >/dev/null 2>&1; then
    PKG=dnf
  elif command -v yum >/dev/null 2>&1; then
    PKG=yum
  else
    echo "未找到 apt-get / dnf / yum。请先自行安装依赖后加 --skip-deps。" >&2
    exit 1
  fi
}

pkg_update() {
  case "$PKG" in
    apt) DEBIAN_FRONTEND=noninteractive apt-get update -y ;;
    dnf) dnf -y makecache ;;
    yum) yum -y makecache ;;
  esac
}

pkg_install() {
  case "$PKG" in
    apt) DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
    dnf) dnf -y install "$@" ;;
    yum) yum -y install "$@" ;;
  esac
}

need_frontend_build() {
  [ -f "$DIR/frontend/package.json" ] || return 1
  [ -d "$DIR/frontend/dist" ] && [ -n "$(ls -A "$DIR/frontend/dist" 2>/dev/null)" ] && return 1
  return 0
}

install_nodejs() {
  if command -v node >/dev/null 2>&1; then
    return 0
  fi
  echo "==> 安装 Node.js 22.x（NodeSource；仅就地构建前端时需要）"
  local setup=""
  case "$PKG" in
    apt) setup="https://deb.nodesource.com/setup_22.x" ;;
    dnf|yum) setup="https://rpm.nodesource.com/setup_22.x" ;;
  esac
  curl -fsSL "$setup" -o /tmp/nodesource-setup.sh
  bash /tmp/nodesource-setup.sh
  rm -f /tmp/nodesource-setup.sh
  pkg_install nodejs
}

github_py() {
  GITHUB_REPO="$GITHUB_REPO" GITHUB_TOKEN="$GITHUB_TOKEN" RELEASE_REF="$RELEASE_REF" \
    python3 - "$@" <<'PY'
import json, os, sys, urllib.request
from urllib.parse import urlparse

repo = os.environ["GITHUB_REPO"]
token = os.environ.get("GITHUB_TOKEN") or ""
ref = (os.environ.get("RELEASE_REF") or "").strip()
cmd = sys.argv[1]

class StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if urlparse(new.full_url).netloc != urlparse(req.full_url).netloc:
            for header in ("Authorization", "authorization"):
                try:
                    new.remove_header(header)
                except KeyError:
                    pass
        return new

def headers(accept):
    h = {
        "Accept": accept,
        "User-Agent": "club-install",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def get(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers=headers(accept))
    opener = urllib.request.build_opener(StripAuthOnRedirect)
    with opener.open(req, timeout=60) as resp:
        return json.load(resp)

def pick(payload):
    tarball = checksum = None
    for asset in payload.get("assets") or []:
        name = asset.get("name") or ""
        if name.endswith(".tar.gz.sha256"):
            checksum = asset
        elif name.startswith("club-") and name.endswith(".tar.gz") and not name.endswith(".tar.gz.sha256"):
            tarball = asset
    if tarball is None or not tarball.get("url"):
        raise SystemExit("latest GitHub release has no club-*.tar.gz asset")
    print(tarball["name"])
    print(tarball["url"])
    print((checksum or {}).get("url") or "")

if cmd == "resolve":
    if ref:
        tag = ref if ref.startswith("club-") else f"club-{ref}"
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        try:
            pick(get(url))
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception:
            pass
        want = ref[5:] if ref.startswith("club-") else ref
        for item in get(f"https://api.github.com/repos/{repo}/releases?per_page=30"):
            for asset in item.get("assets") or []:
                name = asset.get("name") or ""
                if not (name.startswith("club-") and name.endswith(".tar.gz")) or name.endswith(".sha256"):
                    continue
                sha = name[len("club-") : -len(".tar.gz")]
                if sha.startswith(want) or want.startswith(sha):
                    pick(item)
                    raise SystemExit(0)
        raise SystemExit(f"no GitHub release matching {ref}")
    pick(get(f"https://api.github.com/repos/{repo}/releases/latest"))
elif cmd == "download":
    url, dest = sys.argv[2], sys.argv[3]
    req = urllib.request.Request(url, headers=headers("application/octet-stream"))
    opener = urllib.request.build_opener(StripAuthOnRedirect)
    with opener.open(req, timeout=300) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
else:
    raise SystemExit(f"unknown github_py command {cmd}")
PY
}

nginx_layout() {
  if [ -d /etc/nginx/sites-available ]; then
    echo debian
  elif [ -d /etc/nginx/conf.d ] || [ -d /etc/nginx ]; then
    echo rhel
  else
    echo none
  fi
}

write_nginx_site() {
  local layout conf
  layout="$(nginx_layout)"
  local body
  body=$(cat <<NGINX
# 两段协议（docs/operations/deployment.md、ADR 0015）：
#   浏览器 → nginx：HTTP/1.1；有证书后在 listen 上开 HTTP/2（HTTP/3 可选）
#   nginx → gunicorn unix socket：一律 HTTP/1.1（WebSocket Upgrade 也在这一段）
# 不要按路径把 /ws/ 拆成另一种上游协议，也不要对 unix socket 写 proxy_http_version 2。
# 更新器不会改本文件。改完：nginx -t && systemctl reload nginx。

map \$http_upgrade \$connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name $SERVER_NAME;
    client_max_body_size 20M;
    server_tokens off;

    # 静态文件缓存：哈希构建产物（webpack [contenthash]，文件名含 20 位十六进制）→ 1 年 immutable；
    # 其余 /static/（admin / surveyjs / live2d 等）与 /media/ 上传 → 7 天，过期走 ETag 协商（304）。
    # 注意：location 级 add_header 会覆盖 server 级继承——本块进 443 后，若 server 级配了
    # HSTS / Alt-Svc，需在该块内重复声明，否则哈希产物的响应会缺这些头。
    location ~ "^/static/(.+\.[0-9a-f]{20}\..+)$" {
        alias $DIR/staticfiles/\$1;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
    }
    location /static/ {
        alias $DIR/staticfiles/;
        expires 7d;
    }
    # 统一数据根（docs/operations/data-root.md）：采用 data/ 布局时改为 alias $DIR/data/media/;
    location /media/ {
        alias $DIR/media/;
        expires 7d;
    }

    error_page 502 /maintenance.html;
    location = /maintenance.html {
        alias $DIR/static/maintenance.html;
        default_type text/html;
        charset utf-8;
        internal;
    }

    location / {
        proxy_pass http://unix:$DIR/run/gunicorn.sock;
        proxy_http_version 1.1;
        proxy_set_header Upgrade           \$http_upgrade;
        proxy_set_header Connection        \$connection_upgrade;
        proxy_set_header Host              \$host;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 7d;
        proxy_send_timeout 7d;
    }
}

# --- 有证书后启用 HTTP/2：取消注释，并把上面的 location /static/ /media/、error_page 和 location / 拷进本 server。
#     注意：/static/ 哈希产物块自带 add_header，会覆盖 server 级 add_header 继承；
#     在 443 使用时若 server 级配了 HSTS / Alt-Svc，需在该块内重复声明。
#     nginx 1.25.1+ 也可写成 listen 443 ssl; 然后 http2 on;
#     HSTS 只写在 443（HTTP 响应里的 HSTS 浏览器会忽略）。
# server {
#     listen 443 ssl http2;
#     listen [::]:443 ssl http2;
#     server_name $SERVER_NAME;
#     ssl_certificate     /etc/letsencrypt/live/$SERVER_NAME/fullchain.pem;
#     ssl_certificate_key /etc/letsencrypt/live/$SERVER_NAME/privkey.pem;
#     client_max_body_size 20M;
#     server_tokens off;
#     add_header Strict-Transport-Security "max-age=31536000" always;
# }
NGINX
)
  case "$layout" in
    debian)
      echo "==> Nginx（Debian 布局）：/etc/nginx/sites-available/$SERVICE_NAME"
      printf '%s\n' "$body" > "/etc/nginx/sites-available/$SERVICE_NAME"
      ln -sf "/etc/nginx/sites-available/$SERVICE_NAME" "/etc/nginx/sites-enabled/$SERVICE_NAME"
      rm -f /etc/nginx/sites-enabled/default
      ;;
    rhel)
      mkdir -p /etc/nginx/conf.d
      conf="/etc/nginx/conf.d/${SERVICE_NAME}.conf"
      echo "==> Nginx（conf.d 布局，阿里云/RHEL）：$conf"
      printf '%s\n' "$body" > "$conf"
      if [ -f /etc/nginx/conf.d/default.conf ]; then
        mv -f /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.disabled
      fi
      ;;
    *)
      echo "未找到 /etc/nginx。请先安装 nginx 或不要跳过依赖。" >&2
      exit 1
      ;;
  esac
}

selinux_labels() {
  command -v getenforce >/dev/null 2>&1 || return 0
  local mode
  mode="$(getenforce 2>/dev/null || true)"
  case "$mode" in
    Enforcing|Permissive) ;;
    *) return 0 ;;
  esac
  echo "==> SELinux $mode：标记 static/media/run，避免 nginx 502"
  if command -v setsebool >/dev/null 2>&1; then
    setsebool -P httpd_can_network_connect 1 2>/dev/null || true
  fi
  for path in "$DIR/staticfiles" "$DIR/static" "$DIR/media"; do
    [ -e "$path" ] || continue
    chcon -R -t httpd_sys_content_t "$path" 2>/dev/null || true
  done
  mkdir -p "$DIR/run"
  chcon -R -t httpd_var_run_t "$DIR/run" 2>/dev/null || true
}

open_http_firewall() {
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    echo "==> firewalld：放行 http"
    firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
  fi
}

ensure_app_user() {
  if id "$APP_USER" >/dev/null 2>&1; then
    return 0
  fi
  echo "==> 创建服务用户 $APP_USER"
  useradd -r -M -d "$DIR" -s /bin/bash "$APP_USER" 2>/dev/null \
    || useradd -r -d "$DIR" -s /bin/bash "$APP_USER" 2>/dev/null \
    || useradd -d "$DIR" -s /bin/bash "$APP_USER"
}

as_app_user() {
  local script rc
  script="$(mktemp)"
  { echo 'set -euo pipefail'; cat; } > "$script"
  chown "$APP_USER:$APP_USER" "$script"
  sudo -u "$APP_USER" bash "$script"
  rc=$?
  rm -f "$script"
  return $rc
}

guess_site_ip() {
  hostname -I 2>/dev/null | awk '{print $1}' || true
}

derive_frontend_url() {
  if [ -n "${FRONTEND_URL:-}" ]; then
    printf '%s\n' "$FRONTEND_URL"
    return
  fi
  if [ "$SERVER_NAME" != "_" ] && [ -n "$SERVER_NAME" ]; then
    printf 'http://%s\n' "$SERVER_NAME"
    return
  fi
  local ip
  ip="$(guess_site_ip)"
  printf 'http://%s\n' "${ip:-127.0.0.1}"
}

env_get() {
  python3 - "$1" "$DIR/.env" <<'PY'
import pathlib, sys
key, path = sys.argv[1], pathlib.Path(sys.argv[2])
if not path.is_file():
    raise SystemExit(0)
prefix = key + "="
for line in path.read_text(encoding="utf-8").splitlines():
    if line.startswith(prefix):
        print(line[len(prefix):].strip().strip('"').strip("'"), end="")
        break
PY
}

env_set() {
  python3 - "$1" "$2" "$DIR/.env" <<'PY'
import pathlib, re, sys
key, value, path = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3])
text = path.read_text(encoding="utf-8") if path.is_file() else ""
lines = text.splitlines()
pat = re.compile(rf"^{re.escape(key)}=")
found = False
out = []
for line in lines:
    if pat.match(line) and not found:
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    if out and out[-1] != "":
        out.append("")
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

hosts_from_frontend() {
  python3 - "$1" "$2" <<'PY'
from urllib.parse import urlparse
import sys
url, extra = sys.argv[1], sys.argv[2]
hosts = []
host = urlparse(url).hostname
if host:
    hosts.append(host)
if extra and extra != "_":
    hosts.append(extra)
hosts.extend(["127.0.0.1", "localhost"])
# unique, stable order
seen = set()
out = []
for h in hosts:
    if h not in seen:
        seen.add(h)
        out.append(h)
print(",".join(out))
PY
}

configure_env() {
  local current_key current_url current_hosts current_debug origin hosts
  current_key="$(env_get SECRET_KEY || true)"
  if [ -z "$current_key" ]; then
    echo "==> 生成 SECRET_KEY"
    env_set SECRET_KEY "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  else
    echo "==> SECRET_KEY 已有，跳过"
  fi

  origin="$(derive_frontend_url)"
  current_url="$(env_get FRONTEND_URL || true)"
  if [ -z "$current_url" ] || [ "$current_url" = "http://localhost:3000" ]; then
    echo "==> FRONTEND_URL=$origin"
    env_set FRONTEND_URL "$origin"
    FRONTEND_URL="$origin"
  else
    echo "==> FRONTEND_URL 已有（$current_url），跳过"
    FRONTEND_URL="$current_url"
  fi

  current_debug="$(env_get DJANGO_DEBUG || true)"
  # 归一化：空 / 1 / true / yes / on 一律写 0。旧逻辑只覆盖 1/true，
  # `DJANGO_DEBUG=yes` 会原样留在生产（审计 H-6）。
  case "$(printf '%s' "$current_debug" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" in
    ""|1|true|yes|on) env_set DJANGO_DEBUG 0 ;;
  esac

  current_hosts="$(env_get ALLOWED_HOSTS || true)"
  if [ -z "$current_hosts" ]; then
    hosts="$(hosts_from_frontend "$FRONTEND_URL" "$SERVER_NAME")"
    echo "==> ALLOWED_HOSTS=$hosts"
    env_set ALLOWED_HOSTS "$hosts"
  fi
  chmod 600 "$DIR/.env"
  chown "$APP_USER:$APP_USER" "$DIR/.env"
}

ensure_superuser() {
  local exists
  exists="$(as_app_user <<EOF | tr -d '\r' | grep -E '^(yes|no)$' | tail -n 1 || true
export HOME="$APP_HOME"
export PATH="\$HOME/.local/bin:\$PATH"
cd "$DIR"
set -a; . ./.env; set +a
uv run python -c "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup(); from django.contrib.auth import get_user_model as G; print('yes' if G().objects.filter(is_superuser=True).exists() else 'no')"
EOF
)"
  if [ "$exists" = "yes" ]; then
    echo "==> 已有超级用户，跳过创建"
    return 0
  fi
  if [ -z "$SUPERUSER_PASSWORD" ]; then
    SUPERUSER_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
    GENERATED_ADMIN_PASSWORD="$SUPERUSER_PASSWORD"
  fi
  echo "==> 创建超级用户 $SUPERUSER_USERNAME"
  as_app_user <<EOF
export HOME="$APP_HOME"
export PATH="\$HOME/.local/bin:\$PATH"
cd "$DIR"
set -a; . ./.env; set +a
export DJANGO_SUPERUSER_USERNAME=$(printf '%q' "$SUPERUSER_USERNAME")
export DJANGO_SUPERUSER_EMAIL=$(printf '%q' "$SUPERUSER_EMAIL")
export DJANGO_SUPERUSER_PASSWORD=$(printf '%q' "$SUPERUSER_PASSWORD")
uv run python manage.py createsuperuser --noinput
EOF
}

detect_pkg

if [ "$SKIP_DEPS" = 0 ]; then
  echo "==> 包管理器：$PKG"
  pkg_update
  echo "==> 安装系统依赖"
  case "$PKG" in
    apt)
      pkg_install build-essential curl tar gzip git nginx sqlite3 ca-certificates gnupg python3
      ;;
    dnf|yum)
      pkg_install gcc gcc-c++ make curl tar gzip git nginx sqlite ca-certificates gnupg2 python3
      ;;
  esac
fi

if [ "$NEED_DOWNLOAD" = 0 ] && need_frontend_build && [ "$SKIP_DEPS" = 0 ]; then
  install_nodejs
fi

if [ -f "$DIR/manage.py" ]; then
  APP_USER="${APP_USER:-$(stat -c %U "$DIR" 2>/dev/null || true)}"
fi
APP_USER="${APP_USER:-club}"
if [ -z "$APP_USER" ] || [ "$APP_USER" = "root" ]; then
  if [ "$NEED_DOWNLOAD" = 1 ]; then
    APP_USER=club
  else
    echo "❌ 无法确定服务用户：目录属主为 root。请用普通用户持有源码，或显式 APP_USER=用户名。" >&2
    exit 1
  fi
fi

if [ "$INTERACTIVE" = 1 ]; then
  if [ "$SERVER_NAME" = "_" ]; then
    read -rp "站点域名（回车则按 IP 访问）： " _got || true
    [ -n "${_got:-}" ] && SERVER_NAME="$_got"
  fi
  _default_fe="$(derive_frontend_url)"
  read -rp "FRONTEND_URL [${_default_fe}]： " _got || true
  FRONTEND_URL="${_got:-$_default_fe}"
  read -rp "超管用户名 [${SUPERUSER_USERNAME}]： " _got || true
  SUPERUSER_USERNAME="${_got:-$SUPERUSER_USERNAME}"
  read -rp "超管邮箱 [${SUPERUSER_EMAIL}]： " _got || true
  SUPERUSER_EMAIL="${_got:-$SUPERUSER_EMAIL}"
  if [ -z "$SUPERUSER_PASSWORD" ]; then
    read -rsp "超管密码（回车则随机生成）： " SUPERUSER_PASSWORD || true
    echo
  fi
fi
FRONTEND_URL="$(derive_frontend_url)"

echo "解析值："
echo "  安装目录   DIR          = $DIR"
echo "  运行用户   APP_USER     = $APP_USER"
echo "  服务名     SERVICE_NAME = $SERVICE_NAME"
echo "  域名       SERVER_NAME  = $SERVER_NAME  （_ = 任意/IP）"
echo "  FRONTEND_URL            = $FRONTEND_URL"
echo "  超管       USER         = $SUPERUSER_USERNAME  <$SUPERUSER_EMAIL>"
echo "  包管理器               = $PKG"
echo "  来源                   = $([ "$NEED_DOWNLOAD" = 1 ] && echo "GitHub Release $GITHUB_REPO ${RELEASE_REF:-latest}" || echo "本地源码树")"
echo "  系统依赖               = $([ "$SKIP_DEPS" = 1 ] && echo '跳过（--skip-deps）' || echo '安装')"
echo
if [ "$INTERACTIVE" = 1 ]; then
  echo "将以 root 装依赖、写 .env（SECRET_KEY / FRONTEND_URL）、创建超管、写入 systemd/nginx，并启动 $SERVICE_NAME。"
  read -rp "回车继续，Ctrl-C 中止。"
fi

mkdir -p "$DIR"
ensure_app_user

if [ "$NEED_DOWNLOAD" = 1 ]; then
  command -v python3 >/dev/null 2>&1 || { echo "需要 python3 才能解析 GitHub Release JSON。" >&2; exit 1; }
  echo "==> 下载 GitHub Release：$GITHUB_REPO ${RELEASE_REF:-latest}"
  mapfile -t META < <(github_py resolve)
  ARCHIVE_NAME="${META[0]:-}"
  TARBALL_URL="${META[1]:-}"
  CHECKSUM_URL="${META[2]:-}"
  [ -n "$ARCHIVE_NAME" ] && [ -n "$TARBALL_URL" ] || { echo "无法解析 latest release 资产。" >&2; exit 1; }
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  echo "    $ARCHIVE_NAME"
  github_py download "$TARBALL_URL" "$TMP/$ARCHIVE_NAME"
  if [ -n "$CHECKSUM_URL" ]; then
    github_py download "$CHECKSUM_URL" "$TMP/$ARCHIVE_NAME.sha256"
    expected="$(awk '{print $1}' "$TMP/$ARCHIVE_NAME.sha256")"
    actual="$(sha256sum "$TMP/$ARCHIVE_NAME" | awk '{print $1}')"
    if [ "$expected" != "$actual" ]; then
      echo "sha256 不匹配：$actual != $expected" >&2
      exit 1
    fi
  fi
  echo "==> 解压到 $DIR"
  tar -xzf "$TMP/$ARCHIVE_NAME" -C "$DIR"
  mkdir -p "$DIR/backups/releases"
  cp -f "$TMP/$ARCHIVE_NAME" "$DIR/backups/releases/"
  if [ -f "$TMP/$ARCHIVE_NAME.sha256" ]; then
    cp -f "$TMP/$ARCHIVE_NAME.sha256" "$DIR/backups/releases/"
  fi
  rm -rf "$TMP"
  trap - EXIT
fi

[ -f "$DIR/manage.py" ] || { echo "未在 $DIR 找到 manage.py。" >&2; exit 1; }

echo "==> chown -R $APP_USER:$APP_USER $DIR"
chown -R "$APP_USER:$APP_USER" "$DIR"
install -d -o "$APP_USER" -g "$APP_USER" "$DIR/run" "$DIR/backups"

APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
[ -n "$APP_HOME" ] || { echo "用户 $APP_USER 不存在。" >&2; exit 1; }

echo "==> uv sync --frozen（以 $APP_USER 身份）"
as_app_user <<EOF
export HOME="$APP_HOME"
export PATH="\$HOME/.local/bin:\$PATH"
cd "$DIR"
if ! command -v uv >/dev/null 2>&1; then
  curl -fsSL https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
  sh /tmp/uv-install.sh
  rm -f /tmp/uv-install.sh
fi
uv sync --frozen
EOF

if need_frontend_build; then
  echo "==> 前端构建 → frontend/dist/"
  command -v npm >/dev/null 2>&1 || install_nodejs
  as_app_user <<EOF
export HOME="$APP_HOME"
cd "$DIR/frontend"
npm ci
npm run build
EOF
else
  echo "==> 跳过前端构建（已有 frontend/dist）"
fi

if [ ! -f "$DIR/.env" ]; then
  if [ -f "$DIR/.env.example" ]; then
    echo "==> 从 .env.example 复制 .env"
    sudo -u "$APP_USER" cp "$DIR/.env.example" "$DIR/.env"
  else
    sudo -u "$APP_USER" touch "$DIR/.env"
  fi
fi
configure_env

echo "==> migrate + collectstatic"
as_app_user <<EOF
export HOME="$APP_HOME"
export PATH="\$HOME/.local/bin:\$PATH"
cd "$DIR"
set -a; . ./.env; set +a
uv run python manage.py migrate
uv run python manage.py collectstatic --noinput
mkdir -p run
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git rev-parse HEAD > run/applied-release
fi
EOF

ensure_superuser

# 独立安装时把 SHA 从归档名写入 applied-release（updater 靠这个做回滚）
if [ "$NEED_DOWNLOAD" = 1 ] && [ -n "${ARCHIVE_NAME:-}" ]; then
  APPLIED="${ARCHIVE_NAME#club-}"
  APPLIED="${APPLIED%.tar.gz}"
  if [ -n "$APPLIED" ]; then
    echo "$APPLIED" > "$DIR/run/applied-release"
    chown "$APP_USER:$APP_USER" "$DIR/run/applied-release"
  fi
fi

echo "==> 写 /etc/systemd/system/$SERVICE_NAME.service"
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<UNIT
[Unit]
Description=Club Django (Gunicorn)
After=network.target

[Service]
Type=notify
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$DIR
ExecStart=$DIR/start.sh
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT

if [ -f "/etc/systemd/system/${SERVICE_NAME}-updater.service" ]; then
  echo "==> 停用并移除过期的 ${SERVICE_NAME}-updater.service（改由 start.sh 拉起）"
  systemctl disable --now "${SERVICE_NAME}-updater" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}-updater.service"
fi

write_nginx_site
selinux_labels
open_http_firewall
nginx -t
systemctl enable nginx >/dev/null 2>&1 || true
systemctl reload nginx 2>/dev/null || systemctl start nginx

echo "==> 写 /etc/sudoers.d/$SERVICE_NAME（$APP_USER 免密 systemctl $SERVICE_NAME）"
cat > "/etc/sudoers.d/$SERVICE_NAME" <<SUDOERS
$APP_USER ALL=(ALL) NOPASSWD: $SYSTEMCTL start $SERVICE_NAME, $SYSTEMCTL stop $SERVICE_NAME, $SYSTEMCTL restart $SERVICE_NAME, $SYSTEMCTL reload $SERVICE_NAME, $SYSTEMCTL is-active $SERVICE_NAME
SUDOERS
chmod 440 "/etc/sudoers.d/$SERVICE_NAME"
visudo -c -f "/etc/sudoers.d/$SERVICE_NAME"

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

echo
echo "✅ 部署完成。"
echo "   访问： ${FRONTEND_URL:-http://${SERVER_NAME/#_/localhost}}"
echo "   后台： ${FRONTEND_URL%/}/admin/"
echo "   超管： $SUPERUSER_USERNAME  <$SUPERUSER_EMAIL>"
if [ -n "$GENERATED_ADMIN_PASSWORD" ]; then
  echo "   密码： $GENERATED_ADMIN_PASSWORD"
  echo "          ↑ 随机生成，只显示一次，登录后请立刻修改。"
fi
echo "   日志： sudo journalctl -u $SERVICE_NAME -f"
echo "   更新： sudo -u $APP_USER HOME=$APP_HOME bash -lc 'cd \"$DIR\" && set -a;. ./.env;set +a && .venv/bin/python scripts/updater.py --apply-now [SHA]'"
echo "   回滚： sudo -u $APP_USER HOME=$APP_HOME bash -lc 'cd \"$DIR\" && set -a;. ./.env;set +a && .venv/bin/python scripts/updater.py --rollback [SHA]'"
echo
echo "⚠️  可选收尾："
echo "   1) 编辑 $DIR/.env 填 EMAIL_* / TURNSTILE_* / UPDATE_GITHUB_TOKEN，再：sudo systemctl restart $SERVICE_NAME"
echo "   2) /admin/ 把成员加入「社长」「信息组」组（没组=没权限）。"
echo "   3) 夜间窗口/轮询在 /admin/ 「站点策略」。"
echo "   4) 阿里云 SELinux 若仍 502：确认 $DIR/run/gunicorn.sock，并看 journalctl -u nginx / $SERVICE_NAME。"
