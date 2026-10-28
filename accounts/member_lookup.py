"""社员公开查询：按真实姓名 / 社员编号（识别码）查社员，并给出每 24 小时额度（ADR-0025）。

为什么需要额度：识别码是结构化数字，姓名也是可枚举的短词表。扫码页靠 HMAC 签名挡住
「猜码遍历」，但手输查询没法签名（用户没有签名串），所以改用「身份分档 + 24 小时滚动
额度」把枚举成本抬到不可行：

| 查询者 | 每 24 小时上限 |
|---|---|
| 未登录（按 IP） | 3 |
| 已登录未认证 | 10 |
| 已认证的非社员 | 20 |
| 社员 / 认证教师 / 管理员 / 超级管理员 | 不限 |

额度按**滚动 24 小时**计算（与 SimpleRateThrottle 的窗口口径一致）：记下每次查询的时间戳，
窗口内条数达到上限即拒绝；最早一条过期后才腾出名额。**一次请求算一次额度，不论是否命中**——
未命中不计数的话就能无限试错，额度形同虚设。

只看公开字段（姓名 / 届数 / 识别码 / 状态 / 头像），电话、校牌号、学号、邮箱绝不下发，
与扫码校验页完全同源（:func:`public_member_payload`）。
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone as dt_timezone

from django.core.cache import cache

from .models import MemberIdentity, Profile, is_verified
from .utils import get_client_ip

WINDOW_SECONDS = 24 * 60 * 60
WINDOW_HOURS = 24

LIMIT_ANON = 3
LIMIT_UNVERIFIED = 10
LIMIT_VERIFIED = 20

# 同名结果的最大条数（一届名册里同名通常 1–2 人；封顶防大姓名表拖垮响应）
MAX_NAME_MATCHES = 20

_CACHE_PREFIX = "member_lookup:v1"
_CODE_RE = re.compile(r"^\d{8}$")


def lookup_limit(user) -> int | None:
    """该查询者的 24 小时额度；``None`` = 不限。

    判定顺序 = 从最宽到最严：管理员 / 超管 → 社员 → 认证教师 → 已认证 → 未认证。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return LIMIT_ANON
    if user.is_superuser or user.is_staff:
        return None
    if MemberIdentity.objects.filter(user=user).exists():
        return None
    identity = (
        Profile.objects.filter(user=user).values_list("identity", flat=True).first()
    )
    if identity == "teacher" and is_verified(user):
        return None
    return LIMIT_VERIFIED if is_verified(user) else LIMIT_UNVERIFIED


def _cache_key(request, user) -> str:
    """计数键：登录按账号，未登录按 IP 哈希（IP 原文不入缓存键 / 日志）。"""
    if user is not None and getattr(user, "is_authenticated", False):
        ident = f"u{user.pk}"
    else:
        ip = get_client_ip(request) or "unknown"
        ident = "ip" + hashlib.sha256(ip.encode()).hexdigest()[:32]
    return f"{_CACHE_PREFIX}:{ident}"


def _window_history(key: str, now: float) -> list[float]:
    """缓存里仍在 24 小时窗口内的时间戳（旧的顺手丢弃）。"""
    history = [float(t) for t in (cache.get(key) or [])]
    floor = now - WINDOW_SECONDS
    return [t for t in history if t > floor]


def _snapshot(limit: int | None, history: list[float], now: float) -> dict:
    used = len(history) if limit is not None else 0
    reset_at = None
    if limit is not None and history:
        reset_at = datetime.fromtimestamp(min(history) + WINDOW_SECONDS, tz=dt_timezone.utc)
    return {
        "limit": limit,  # None = 不限
        "used": used,
        "remaining": None if limit is None else max(0, limit - used),
        "reset_at": reset_at.isoformat() if reset_at else None,
        "window_hours": WINDOW_HOURS,
    }


def quota_snapshot(request) -> dict:
    """只读额度（GET 用，不计数）。"""
    user = getattr(request, "user", None)
    limit = lookup_limit(user)
    if limit is None:
        return _snapshot(None, [], time.time())
    now = time.time()
    return _snapshot(limit, _window_history(_cache_key(request, user), now), now)


def consume(request) -> tuple[bool, dict]:
    """记一次查询。返回 ``(是否放行, 额度快照)``；被拒时快照里的 remaining = 0。"""
    user = getattr(request, "user", None)
    limit = lookup_limit(user)
    if limit is None:
        return True, _snapshot(None, [], time.time())

    now = time.time()
    key = _cache_key(request, user)
    history = _window_history(key, now)
    if len(history) >= limit:
        return False, _snapshot(limit, history, now)

    history.append(now)
    # 缓存 TTL 取「最早一条过期」的剩余时长，避免无限增长
    cache.set(key, history, WINDOW_SECONDS)
    return True, _snapshot(limit, history, now)


def retry_after(snapshot: dict) -> int:
    """距离下一次名额释放的秒数（无 reset_at 时为 0）。"""
    raw = snapshot.get("reset_at")
    if not raw:
        return 0
    try:
        reset_at = datetime.fromisoformat(raw)
    except ValueError:
        return 0
    remaining = (reset_at - datetime.now(tz=dt_timezone.utc)).total_seconds()
    return max(0, int(remaining))


def search_members(query: str) -> list[MemberIdentity]:
    """按「8 位数字社员编号」或「完整真实姓名」查名册；不做前缀 / 模糊匹配。

    模糊匹配等于把整本名册交出去，额度再严也没意义；姓名必须**完全一致**。
    """
    q = (query or "").strip()
    if not q or len(q) > 100:
        return []
    if _CODE_RE.match(q):
        return list(MemberIdentity.objects.filter(code=q)[:1])
    rows = list(
        MemberIdentity.objects.filter(name=q).order_by("-cohort", "code")[:MAX_NAME_MATCHES]
    )
    if not rows:
        # 英文 / 混排姓名大小写不敏感（中文 iexact 与精确一致，多一次查询仅发生在未命中）
        rows = list(
            MemberIdentity.objects.filter(name__iexact=q).order_by("-cohort", "code")[
                :MAX_NAME_MATCHES
            ]
        )
    return rows


def public_member_payload(row: MemberIdentity) -> dict:
    """扫码页与查询页共用的最小公开字段（电话 / 校牌号 / 学号 / 邮箱绝不出现）。"""
    avatar_url = None
    if row.user_id:
        profile = Profile.objects.filter(user_id=row.user_id).first()
        if profile is not None and profile.avatar:
            avatar_url = profile.avatar.url
    return {
        "name": row.name,
        "cohort": row.cohort,
        "code": row.code,
        "status": row.status,
        "avatar": avatar_url,
    }


__all__ = [
    "LIMIT_ANON",
    "LIMIT_UNVERIFIED",
    "LIMIT_VERIFIED",
    "WINDOW_HOURS",
    "consume",
    "lookup_limit",
    "public_member_payload",
    "quota_snapshot",
    "retry_after",
    "search_members",
]
