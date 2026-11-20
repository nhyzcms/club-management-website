#!/usr/bin/env bash
# install-docker-host.sh — 把一台裸机生产环境改造成「容器化运行 + CI 推送部署」。
#
# 只做一次。之后所有发布都由 CD 流水线完成。
#
#   sudo ./scripts/install-docker-host.sh --check            # 只体检，不改任何东西
#   sudo ./scripts/install-docker-host.sh --yes --deploy-key-file /root/deploy.pub
#   sudo ./scripts/install-docker-host.sh --yes --cutover sha-<sha>   # 装完立刻切到容器
#
# 刻意不做的事：
#   - 不动 nginx（它只认 /opt/club/run/gunicorn.sock、/opt/club/staticfiles、/opt/club/data）
#   - 不动 PostgreSQL / pgbouncer / Redis（留宿主机，容器走 host 网络直连 127.0.0.1）
#   - 不删旧的 /opt/club 源码树（回滚要它；确认稳定后再单独清理）
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-clubdeploy}"
APP_DIR="${APP_DIR:-/opt/club}"
DOCKER_REPO_FILE=/etc/yum.repos.d/docker-ce.repo
MIRROR="${DOCKER_CE_MIRROR:-https://mirrors.aliyun.com/docker-ce/linux/centos}"

MODE=check
ASSUME_YES=0
DEPLOY_PUBKEY_FILE=""
CUTOVER_TAG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE=check ;;
    --yes|-y) ASSUME_YES=1; MODE=apply ;;
    --deploy-key-file) DEPLOY_PUBKEY_FILE="${2:?}"; shift ;;
    --cutover) CUTOVER_TAG="${2:?}"; shift ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
info() { printf '   %s\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "须以 root 运行"

# ── 体检 ────────────────────────────────────────────────────────────────
say "环境体检"
. /etc/os-release
info "系统：$PRETTY_NAME"
info "内存：$(awk '/MemTotal/{printf "%d MB 总", $2/1024}' /proc/meminfo)，可用 $(awk '/MemAvailable/{printf "%d MB", $2/1024}' /proc/meminfo)"
info "磁盘：$(df -h / | awk 'NR==2{print $4" 可用 / "$2" 总"}')"
command -v nginx >/dev/null && info "nginx：$(nginx -v 2>&1)"
command -v pg_dump >/dev/null && info "pg_dump：$(pg_dump --version)" || info "pg_dump：未安装（数据库备份会跳过）"
[ -f "$APP_DIR/.env" ] || die "缺少 $APP_DIR/.env"
[ -f "$APP_DIR/docker-compose.yml" ] || info "compose 文件尚未安装（apply 阶段会装）"
if command -v docker >/dev/null; then
  info "docker：$(docker --version)"
  docker compose version >/dev/null 2>&1 && info "compose：$(docker compose version --short)"
  [ "$MODE" = "check" ] || [ "$ASSUME_YES" = "1" ] || die "docker 已存在但未加 --yes"
fi
if systemctl is-active --quiet club.service 2>/dev/null; then
  info "旧 systemd unit club.service：运行中（cutover 时会停止并禁用）"
fi

if [ "$MODE" = "check" ]; then
  say "仅体检模式，未做任何改动。确认无误后加 --yes 执行。"
  exit 0
fi

# ── Docker ─────────────────────────────────────────────────────────────
say "安装 Docker Engine"
if ! command -v docker >/dev/null; then
  # Alibaba Cloud Linux 3 的仓库里没有 docker，只有 podman；用 docker 官方源（走阿里云镜像）
  EL_VER=8
  . /etc/os-release
  case "${VERSION_ID%%.*}" in
    9) EL_VER=9 ;;
  esac
  if [ ! -f "$DOCKER_REPO_FILE" ]; then
    info "写入 $DOCKER_REPO_FILE（el${EL_VER}，镜像源 $MIRROR）"
    cat >"$DOCKER_REPO_FILE" <<EOF
[docker-ce-stable]
name=Docker CE Stable - \$basearch
baseurl=${MIRROR}/${EL_VER}/\$basearch/stable
enabled=1
gpgcheck=1
gpgkey=${MIRROR}/gpg
EOF
  fi
  dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
    || die "docker 安装失败"
else
  info "docker 已安装，跳过"
fi

systemctl enable --now docker
docker info >/dev/null || die "docker daemon 未正常启动"

# 国内直连 Docker Hub 会被掐；只在「本机要拉 Docker Hub 镜像」时才需要镜像加速。
# 生产只拉 ghcr.io，这条只是给手工排障留的余地。
if [ -n "${DOCKER_HUB_MIRROR:-}" ]; then
  mkdir -p /etc/docker
  python3 - "$DOCKER_HUB_MIRROR" <<'PY'
import json, sys, pathlib
p = pathlib.Path("/etc/docker/daemon.json")
data = {}
if p.exists():
    try: data = json.loads(p.read_text())
    except Exception: data = {}
data.setdefault("registry-mirrors", [])
if sys.argv[1] not in data["registry-mirrors"]:
    data["registry-mirrors"].append(sys.argv[1])
p.write_text(json.dumps(data, indent=2))
PY
  systemctl restart docker
  info "已配置 Docker Hub 镜像：$DOCKER_HUB_MIRROR"
fi

docker compose version >/dev/null || die "docker compose 插件缺失"

# ── 部署用户 ────────────────────────────────────────────────────────────
say "部署用户 $DEPLOY_USER"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$DEPLOY_USER"
  info "已创建用户"
else
  info "用户已存在"
fi
usermod -aG docker "$DEPLOY_USER"
info "已加入 docker 组（该组等价 root 权限，因此 CI 侧密钥必须配强制命令）"

# ── 目录与权限 ──────────────────────────────────────────────────────────
say "运行期目录"
install -d -o root -g "$DEPLOY_USER" -m 2775 "$APP_DIR/run"
install -d -o root -g "$DEPLOY_USER" -m 2775 "$APP_DIR/backups"
install -d -o root -g "$DEPLOY_USER" -m 2775 "$APP_DIR/backups/db"
install -d -o root -g root -m 755 "$APP_DIR/staticfiles"
install -d -o root -g root -m 755 "$APP_DIR/scripts"
# deploy.sh 需要读 .env 里的数据库口令做备份
chown root:"$DEPLOY_USER" "$APP_DIR/.env"
chmod 640 "$APP_DIR/.env"
info "run / backups 归 $DEPLOY_USER；.env 640 root:$DEPLOY_USER"

# ── 安装 compose / deploy.sh / wrapper ──────────────────────────────────
say "安装部署脚本"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

install -m 644 "$REPO_ROOT/deploy/docker-compose.yml" "$APP_DIR/docker-compose.yml"
install -m 755 "$SCRIPT_DIR/deploy.sh" "$APP_DIR/scripts/deploy.sh"
install -m 755 "$SCRIPT_DIR/deploy-wrapper.sh" "$APP_DIR/scripts/deploy-wrapper.sh"
info "compose → $APP_DIR/docker-compose.yml"
info "deploy  → $APP_DIR/scripts/deploy.sh"

install -d -m 755 /var/log
: >/var/log/club-deploy.log
chown root:"$DEPLOY_USER" /var/log/club-deploy.log
chmod 664 /var/log/club-deploy.log

# ── systemd timer（窗口内自动切换）───────────────────────────────────────
say "窗口切换定时器"
cat >/etc/systemd/system/club-deploy.service <<EOF
[Unit]
Description=Club container deploy (apply pending image inside window)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=$DEPLOY_USER
Group=$DEPLOY_USER
ExecStart=$APP_DIR/scripts/deploy.sh tick
Nice=10
EOF

cat >/etc/systemd/system/club-deploy.timer <<'EOF'
[Unit]
Description=Check for a pending club image every 5 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now club-deploy.timer
info "club-deploy.timer 每 5 分钟检查一次待发布镜像"

# ── SSH 强制命令 ────────────────────────────────────────────────────────
if [ -n "$DEPLOY_PUBKEY_FILE" ]; then
  say "安装 CI 部署公钥"
  [ -f "$DEPLOY_PUBKEY_FILE" ] || die "公钥文件不存在：$DEPLOY_PUBKEY_FILE"
  install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 700 "/home/$DEPLOY_USER/.ssh"
  AK="/home/$DEPLOY_USER/.ssh/authorized_keys"
  touch "$AK"
  KEY="$(cat "$DEPLOY_PUBKEY_FILE")"
  # restrict = 关闭 pty / 端口转发 / agent 转发 / X11；命令被强制到 wrapper
  ENTRY="restrict,command=\"$APP_DIR/scripts/deploy-wrapper.sh\" $KEY"
  if grep -qF "$KEY" "$AK" 2>/dev/null; then
    info "该公钥已存在，替换旧条目"
    grep -vF "$KEY" "$AK" >"$AK.tmp" || true
    mv "$AK.tmp" "$AK"
  fi
  printf '%s\n' "$ENTRY" >>"$AK"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$AK"
  chmod 600 "$AK"
  info "已写入 $AK（强制命令，无交互式 shell）"
fi

# ── 切流 ────────────────────────────────────────────────────────────────
if [ -n "$CUTOVER_TAG" ]; then
  say "切换到容器运行：$CUTOVER_TAG"
  info "停止并禁用旧 unit club.service（它和容器会抢同一个 gunicorn.sock）"
  systemctl stop club.service || true
  systemctl disable club.service || true

  su - "$DEPLOY_USER" -c "$APP_DIR/scripts/deploy.sh now '$CUTOVER_TAG'"

  say "切流完成"
  info "nginx 不需要改：依然反代 $APP_DIR/run/gunicorn.sock"
  info "自检：curl -sk --noproxy '*' https://127.0.0.1/site-policy/ | head -c 120"
fi

say "完成"
info "查看状态：sudo -u $DEPLOY_USER $APP_DIR/scripts/deploy.sh status"
info "手动立即部署：sudo -u $DEPLOY_USER $APP_DIR/scripts/deploy.sh now sha-<sha>"
info "回滚：sudo -u $DEPLOY_USER $APP_DIR/scripts/deploy.sh rollback"
