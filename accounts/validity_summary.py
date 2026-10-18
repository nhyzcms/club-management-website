"""账号有效期展示口径（只读快照 + 一次性提示键）。

与相邻模块的分工：

- ``accounts.validity``：**执行**规则（管理员过期撤销、未认证超期停用）；
- ``accounts.validity_notices``：到期**前**两个月 / 一个月的站内提醒（台账防重）；
- 本模块：**读**当前状态，算出「现在是什么身份、什么时候到期、还剩多少天」，
  供 ``GET /auth/validity/`` 前端弹窗 / 认证面板与 ``send_validity_broadcast``
  群发私信共用。纯函数，不写库。

一次性提示（注册后 / 认证通过后弹窗一次）：``Profile.validity_notice_ack`` 存用户
已读的**快照键**。键由「状态 + 到期时间」拼成（``verified:2027-10-18T12:00:00+08:00``），
状态变化（未认证 → 已认证）或到期时间变化（续期）时键自然改变 → 弹窗重新出现；
用户点「我知道了」把当前键写回，之后不再打扰。跨设备一致（存服务端，非 localStorage）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone

from common.policy import get_policy

from .models import (
    Profile,
    Verification,
    admin_identity_valid,
    has_ever_verified,
    is_verified,
    profile_of,
    registration_verify_days,
)
from .validity_notices import channel_label

STATUS_PERMANENT = "permanent"
STATUS_ADMIN = "admin"
STATUS_VERIFIED = "verified"
STATUS_EXPIRED = "expired"
STATUS_UNVERIFIED = "unverified"

STATUS_LABELS = {
    STATUS_PERMANENT: "超级管理员（永久有效）",
    STATUS_ADMIN: "管理员",
    STATUS_VERIFIED: "已认证用户",
    STATUS_EXPIRED: "认证已到期",
    STATUS_UNVERIFIED: "未认证用户",
}


def registration_deadline(user, profile=None) -> datetime:
    """未认证账号的认证截止：``Profile.registration_deadline`` 覆盖 > 注册日 + 宽限天数。"""
    profile = profile if profile is not None else profile_of(user)
    if profile is not None and profile.registration_deadline is not None:
        return profile.registration_deadline
    return user.date_joined + timedelta(days=registration_verify_days())


def remaining_days(expires_at, now=None) -> int | None:
    """距到期的整天数（向下取整，可能为负）；``None`` = 永久有效。

    加 1 秒容差：刚建好的 60 天宽限 / 刚通过的 365 天认证应显示 60 / 365 天，而不是
    因为几十微秒的差被算成 59 / 364。不足 24 小时且未到期返回 0（前端显示「不足 1 天」）。
    """
    if expires_at is None:
        return None
    now = now or timezone.now()
    return (expires_at + timedelta(seconds=1) - now).days


def _active_channels(user, now) -> list[dict]:
    """未过期的 approved 通道，按到期时间升序（永久排最后）。"""
    rows = [
        row
        for row in user.verifications.all()
        if row.status == Verification.STATUS_APPROVED
        and (row.expires_at is None or row.expires_at > now)
    ]
    rows.sort(key=lambda row: (row.expires_at is None, row.expires_at or now))
    return [
        {
            "channel": row.channel,
            "label": channel_label(row.channel),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "remaining_days": remaining_days(row.expires_at, now),
        }
        for row in rows
    ]


def _latest_expired_at(user, now):
    """最近一次已过期的 approved 通道到期时间（无则 None）。"""
    expired = [
        row.expires_at
        for row in user.verifications.all()
        if row.status == Verification.STATUS_APPROVED
        and row.expires_at is not None
        and row.expires_at <= now
    ]
    return max(expired) if expired else None


def account_validity(user, now=None) -> dict:
    """账号有效期快照（前端弹窗 / 认证面板 / 群发私信的唯一口径）。"""
    now = now or timezone.now()
    policy = get_policy()
    profile = profile_of(user)

    channels: list[dict] = []
    expires_at = None
    deadline = None

    if user.is_superuser:
        # 超管委任通道 expires_at=null（永久），按设计豁免所有有效期规则。
        status = STATUS_PERMANENT
        channels = _active_channels(user, now)
    elif admin_identity_valid(user):
        status = STATUS_ADMIN
        channels = _active_channels(user, now)
        appointment = next(
            (row for row in user.verifications.all()
             if row.channel == Verification.CHANNEL_APPOINTMENT
             and row.status == Verification.STATUS_APPROVED),
            None,
        )
        if appointment is None or appointment.expires_at is None:
            status = STATUS_PERMANENT
        else:
            expires_at = appointment.expires_at
    elif is_verified(user):
        status = STATUS_VERIFIED
        channels = _active_channels(user, now)
        # 账号在「最后一个有效通道」到期时才失去认证；任一永久 → 永久。
        if channels and all(item["expires_at"] is not None for item in channels):
            expires_at = max(datetime.fromisoformat(item["expires_at"]) for item in channels)
    elif has_ever_verified(user):
        status = STATUS_EXPIRED
        expires_at = _latest_expired_at(user, now)
    else:
        status = STATUS_UNVERIFIED
        deadline = registration_deadline(user, profile)
        expires_at = deadline

    key = _notice_key(status, expires_at)
    ack = getattr(profile, "validity_notice_ack", "") if profile is not None else ""
    return {
        "status": status,
        "status_label": STATUS_LABELS[status],
        "expires_at": expires_at.isoformat() if expires_at else None,
        "remaining_days": remaining_days(expires_at, now),
        "registration_deadline": deadline.isoformat() if deadline else None,
        "channels": channels,
        "policy": {
            "verification_valid_days": policy.verification_valid_days,
            "admin_valid_days": policy.admin_valid_days,
            "registration_verify_days": policy.registration_verify_days,
        },
        "key": key,
        "notice_pending": ack != key,
    }


def _notice_key(status: str, expires_at) -> str:
    """一次性提示的快照键：状态变化或到期时间变化都会换成新键。"""
    if status == STATUS_PERMANENT or expires_at is None:
        return f"{status}:forever"
    return f"{status}:{expires_at.isoformat()}"


def ack_notice(user, key: str) -> bool:
    """把「已读」写回当前快照键；键与当前状态不一致时不写（返回 False）。"""
    current = account_validity(user)["key"]
    if key != current:
        return False
    profile, _ = Profile.objects.get_or_create(user=user)
    if profile.validity_notice_ack != key:
        profile.validity_notice_ack = key
        profile.save(update_fields=["validity_notice_ack"])
    return True


# ---- 群发私信文案 ---------------------------------------------------------


def _format_moment(value) -> str:
    if value is None:
        return "永久有效"
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


def _format_remaining(days: int | None, expires_at) -> str:
    if days is None:
        return "永久有效"
    if days > 0:
        return f"{days} 天"
    if expires_at is not None and expires_at > timezone.now():
        return "不足 1 天"
    return "已到期"


def format_dm_message(user, validity: dict) -> str:
    """站内私信正文：到期时间 + 剩余有效期 + 规则（按账号当前状态裁剪）。"""
    profile = profile_of(user)
    nickname = (profile.nickname if profile is not None else "") or user.username
    status = validity["status"]
    policy = validity["policy"]
    expires_at = datetime.fromisoformat(validity["expires_at"]) if validity["expires_at"] else None

    if status == STATUS_PERMANENT:
        expires_label = "账号到期时间"
        expires_text = "永久有效（不设到期时间）"
        remaining_text = "永久有效"
    elif status == STATUS_UNVERIFIED:
        expires_label = "认证截止时间"
        expires_text = _format_moment(expires_at)
        remaining_text = _format_remaining(validity["remaining_days"], expires_at)
    elif status == STATUS_ADMIN:
        expires_label = "管理员身份到期时间"
        expires_text = _format_moment(expires_at)
        remaining_text = _format_remaining(validity["remaining_days"], expires_at)
    else:  # verified / expired
        expires_label = "账号到期时间"
        expires_text = _format_moment(expires_at)
        remaining_text = _format_remaining(validity["remaining_days"], expires_at)

    lines = [
        "【账号有效期说明】",
        f"你好，{nickname}！",
        "",
        f"你的账号当前状态：{validity['status_label']}",
        f"{expires_label}：{expires_text}",
        f"剩余有效期：{remaining_text}",
        "",
        "有效期规则：",
        f"1. 认证有效期 {policy['verification_valid_days']} 天：完成邮箱认证 / 学生证人工核验 / "
        f"认证码兑换中任一通道后生效；到期后账号回落为未认证，需要重新认证。",
        f"2. 管理员委任有效期 {policy['admin_valid_days']} 天：到期自动撤销管理员身份；"
        "超级管理员永久有效。",
        f"3. 注册宽限 {policy['registration_verify_days']} 天：注册后须在宽限期内完成任一认证，"
        "逾期未认证的账号将被停用（需联系管理员恢复）。",
        "",
        "可在「个人中心 → 账号认证」查看认证状态；到期后重新完成认证即可恢复。",
    ]
    return "\n".join(lines)
