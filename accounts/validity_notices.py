"""身份到期前的站内提醒（降权预警）：认证 / 管理员身份「还剩两个月 / 一个月」。

只提醒会导致**降权**的到期（需求范围）：

- 认证通道有效期到 → 账号从「已认证」回落「未认证」；
- 管理员委任有效期到 → 撤销 ``is_staff``（回落普通用户）。

超管委任 ``expires_at=null``（永久）永不提醒；「注册后未认证会被停用」不在本模块范围
（那走 ``accounts.validity`` 的停用流程）。

两个档位各发一次，同一到期时间只发**最紧迫**的那一档：首次扫描时若只剩 20 天，
就只发「还剩一个月」——已过去的窗口不补发。台账 ``ValidityNotice``（通道行 × 到期时间 ×
档位）保证只发一次；到期时间被改写（续期）后重新起算。

幂等、可重复执行；``dry_run=True`` 只统计不落库（供 ``manage.py enforce_validity --dry-run``）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from messaging.services import notify

from .models import ValidityNotice, Verification


@dataclass(frozen=True)
class NoticeLevel:
    """一个提醒档位：台账 key、触发天数、通知事件、中文档位名。"""

    key: str
    days: int
    event: str
    label: str


LEVELS = (
    NoticeLevel(ValidityNotice.LEVEL_60D, 60, "expiring_2m", "还剩两个月"),
    NoticeLevel(ValidityNotice.LEVEL_30D, 30, "expiring_1m", "还剩一个月"),
)
HORIZON_DAYS = max(level.days for level in LEVELS)

# 通知源 key（与 messaging.notifications.sources.ValiditySource 一致）。
CATEGORY = "validity"

_CHANNEL_LABELS = {
    Verification.CHANNEL_APPOINTMENT: "管理员身份",
    Verification.CHANNEL_EMAIL: "邮箱认证",
    Verification.CHANNEL_MANUAL: "人工认证",
    Verification.CHANNEL_AUTHCODE: "认证码认证",
}


def channel_label(channel: str) -> str:
    """通道 → 通知里显示的短名（如「管理员身份」「邮箱认证」）。"""
    return _CHANNEL_LABELS.get(channel, "身份认证")


def due_levels(expires_at, now) -> list[NoticeLevel]:
    """已进入提醒窗口的档位（到期越近，档位天数越小）。"""
    return [level for level in LEVELS if expires_at <= now + timedelta(days=level.days)]


def pending_level(expires_at, now, sent_levels) -> NoticeLevel | None:
    """本次该发的档位：已进入窗口、且比已发过的档位更紧迫；没有则 ``None``。

    ``sent_levels`` 是该 (通道行, 到期时间) 已发的档位 key 集。已发过更紧迫（天数更小）
    的档位即视为旧档位已作废，不补发过时提醒。
    """
    due = due_levels(expires_at, now)
    if not due:
        return None
    sent_days = [level.days for level in LEVELS if level.key in sent_levels]
    floor = min(sent_days) if sent_days else None
    pending = [level for level in due if floor is None or level.days < floor]
    if not pending:
        return None
    return min(pending, key=lambda level: level.days)


def expiring_verifications(now=None):
    """进入提醒窗口（未过期、``HORIZON_DAYS`` 内到期）的 approved 通道行。"""
    now = now or timezone.now()
    return (
        Verification.objects
        .filter(
            status=Verification.STATUS_APPROVED,
            expires_at__isnull=False,
            expires_at__gt=now,
            expires_at__lte=now + timedelta(days=HORIZON_DAYS),
        )
        .select_related("user")
        .order_by("expires_at", "pk")
    )


def sent_levels(verification) -> set[str]:
    """该通道行在**当前到期时间**上已落账的档位。"""
    return set(
        ValidityNotice.objects
        .filter(verification=verification, expires_at=verification.expires_at)
        .values_list("level", flat=True)
    )


def send_expiry_notices(now=None, dry_run=False) -> dict:
    """扫描并投递到期提醒，返回 ``{事件: 条数}``（dry_run 时只统计）。"""
    now = now or timezone.now()
    counts = {level.event: 0 for level in LEVELS}
    for verification in expiring_verifications(now):
        user = verification.user
        if not user.is_active:
            continue
        level = pending_level(verification.expires_at, now, sent_levels(verification))
        if level is None:
            continue
        if dry_run:
            counts[level.event] += 1
            continue
        row = notify(user, CATEGORY, level.event, payload=_payload(verification, level, now))
        if row is None:
            # 用户关闭了该源的站内通道（拒绝接收）：不落账，重新开启后仍能收到。
            continue
        ValidityNotice.objects.get_or_create(
            verification=verification,
            expires_at=verification.expires_at,
            level=level.key,
        )
        counts[level.event] += 1
    return counts


def _payload(verification, level, now) -> dict:
    """通知载荷：通道、到期日、剩余天数、跳转（认证面板）。"""
    expires_on = timezone.localtime(verification.expires_at).date().isoformat()
    return {
        "channel": verification.channel,
        "channel_label": channel_label(verification.channel),
        "level": level.key,
        "expires_on": expires_on,
        "days_left": (verification.expires_at - now).days,
        "url": "/profile?tab=verification",
    }
