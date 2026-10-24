import re
import secrets
import time

from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from .models import UserSession

SESSION_HISTORY_LIMIT = 20  # 每用户保留的登录记录条数（含在线设备）
# 同时保持登录态的设备上限（多端登录，ADR-0028）。全局名额，不区分客户端类型：
# 网页 / 手机浏览器 / App 各登录一次，正好占满 3 台。
MAX_ACTIVE_SESSIONS = 3
# 设备标识 Cookie：同一台设备重新登录时复用自己的名额，避免一台手机占掉多个名额。
DEVICE_COOKIE_NAME = "club_device"
DEVICE_COOKIE_MAX_AGE = 2 * 365 * 24 * 3600
# 在线设备的「最后活跃」写库节流（秒）：正常浏览时每 2 分钟最多一次 UPDATE。
TOUCH_INTERVAL_SECONDS = 120
APP_UA_TOKEN = "NhyzClubApp/"  # App 壳 UA（见 App 仓库 WebShellClient）

_BOT_RE = re.compile(r"bot|crawl|spider|slurp|fetcher", re.I)
_TABLET_RE = re.compile(r"iPad|Android(?!.*Mobile)|Silk|Kindle|PlayBook", re.I)
_MOBILE_RE = re.compile(r"Android|iPhone|iPod|Mobile|Windows Phone|BlackBerry", re.I)
_BROWSER_RE = re.compile(r"(Edge|Edg|OPR|Opera|Chrome|Chromium|Firefox|Safari|MSIE|Trident)[/ ]([\d.]+)")
_OS_RE = re.compile(r"(Windows NT|Windows \w+|Mac OS X|iPhone OS|Android|Linux)")


def get_client_ip(request):
    """取真实客户端 IP。

    生产走 Caddy 同机反代 → ``REMOTE_ADDR`` 恒为 127.0.0.1，真实 IP 在
    ``X-Forwarded-For`` 第一跳。**只在来源是回环代理时信任 XFF**，避免外部直接
    伪造请求头把登录记录写歪。
    """
    remote = request.META.get("REMOTE_ADDR")
    if remote in {"127.0.0.1", "::1"}:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    return remote


def parse_user_agent(ua):
    if not ua:
        return "Unknown", ""
    if _BOT_RE.search(ua):
        device_type = "Bot"
    elif _TABLET_RE.search(ua):
        device_type = "Tablet"
    elif _MOBILE_RE.search(ua):
        device_type = "Mobile"
    else:
        device_type = "Desktop"

    browser = ""
    m = _BROWSER_RE.search(ua)
    if m:
        name = {"Edg": "Edge", "OPR": "Opera", "MSIE": "IE", "Trident": "IE"}.get(m.group(1), m.group(1))
        browser = name

    os_name = ""
    o = _OS_RE.search(ua)
    if o:
        raw = o.group(1)
        if raw.startswith("Windows"):
            os_name = "Windows"
        elif raw.startswith("Mac OS X"):
            os_name = "macOS"
        elif raw.startswith("iPhone OS"):
            os_name = "iOS"
        elif raw.startswith("Android"):
            os_name = "Android"
        elif raw.startswith("Linux"):
            os_name = "Linux"
        else:
            os_name = raw

    device_name = " · ".join(p for p in (browser, os_name) if p)
    return device_type, device_name


def detect_client_kind(ua, device_type=None):
    """客户端类型：app / mobile / web（个人中心「登录设备」按此显示图标与名称）。"""
    if APP_UA_TOKEN in (ua or ""):
        return "app"
    if device_type is None:
        device_type, _ = parse_user_agent(ua)
    return "mobile" if device_type in ("Mobile", "Tablet") else "web"


def new_device_id():
    return secrets.token_hex(16)


def device_id_from_request(request):
    return (request.COOKIES.get(DEVICE_COOKIE_NAME) or "").strip()[:40]


def _activity_at(row):
    """顶替排序键：最后活跃时间，缺省回落到登录时间。"""
    return row.last_seen_at or row.created_at


@transaction.atomic
def record_user_session(request, user, session_key):
    """登记（或刷新）本次登录的设备，并把在线设备收敛到 ``MAX_ACTIVE_SESSIONS``。

    顶替规则（ADR-0028）：
    1. 同一 ``device_id`` 的旧会话先让位（同一台设备重新登录不额外占名额）；
    2. 仍超出上限时，顶掉**最久未活动**的在线设备（新登录的这台永不顶自己）；
    3. 顶替只写 ``revoked_at`` / ``replaced_by_session_key``，不删 Django Session，
       让被顶设备的下一次请求能拿到 401 + 接管设备信息（前端弹「已被迫下线」）。
    """
    ip = get_client_ip(request)
    ua = request.META.get("HTTP_USER_AGENT", "")
    device_type, device_name = parse_user_agent(ua)
    client_kind = detect_client_kind(ua, device_type)
    device_id = device_id_from_request(request)
    now = timezone.now()

    if device_id:
        UserSession.objects.filter(
            user=user, device_id=device_id, revoked_at__isnull=True
        ).exclude(session_key=session_key).update(
            revoked_at=now,
            revoked_reason=UserSession.REVOKE_REPLACED,
            replaced_by_session_key=session_key,
        )

    UserSession.objects.update_or_create(
        session_key=session_key,
        defaults={
            "user": user,
            "ip_address": ip,
            "user_agent": ua,
            "device_type": device_type,
            "device_name": device_name,
            "client_kind": client_kind,
            "device_id": device_id,
            "last_seen_at": now,
            "revoked_at": None,
            "revoked_reason": "",
            "replaced_by_session_key": "",
        },
    )
    _enforce_active_limit(user, session_key, now)
    _prune_history(user)


def _enforce_active_limit(user, keep_session_key, now):
    """在线设备超过 ``MAX_ACTIVE_SESSIONS`` 时，顶掉最久未活动的那几台。"""
    others = list(
        UserSession.objects.filter(user=user, revoked_at__isnull=True)
        .exclude(session_key=keep_session_key)
    )
    overflow = len(others) + 1 - MAX_ACTIVE_SESSIONS
    if overflow <= 0:
        return
    others.sort(key=_activity_at)
    doomed = [row.id for row in others[:overflow] if row.id]
    if doomed:
        UserSession.objects.filter(id__in=doomed).update(
            revoked_at=now,
            revoked_reason=UserSession.REVOKE_LIMIT,
            replaced_by_session_key=keep_session_key,
        )


def _prune_history(user):
    """裁剪历史：保留最近 ``SESSION_HISTORY_LIMIT`` 条 + 全部在线设备（及其 Django Session）。"""
    base = UserSession.objects.filter(user=user)
    keep_ids = set(
        base.order_by("-created_at", "-id")
        .values_list("id", flat=True)[:SESSION_HISTORY_LIMIT]
    )
    keep_ids |= set(
        base.filter(revoked_at__isnull=True).values_list("id", flat=True)
    )
    extra = base.exclude(id__in=keep_ids)
    keys = list(extra.values_list("session_key", flat=True))
    extra.delete()
    if keys:
        Session.objects.filter(session_key__in=keys).delete()


def touch_user_session(request, row):
    """刷新在线设备的最后活跃时间（会话内节流，避免每请求一次 UPDATE）。"""
    now_ts = time.time()
    last = request.session.get("_us_touched_at") or 0
    if now_ts - last < TOUCH_INTERVAL_SECONDS:
        return
    UserSession.objects.filter(pk=row.pk).update(last_seen_at=timezone.now())
    request.session["_us_touched_at"] = now_ts
