"""全站禁言（纪律处罚）——归属审核模块。

规则：
- 生效 = 最新一行 ``lifted_at`` 为空且（``ends_at`` 为空或未到期）；到期惰性解除。
- 权限：``reviews.mute_user``；举报成立的路径（mute_user_for_report）跳权限，仅供 report_lifecycle 调用。
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from messaging.services import MessagingError, MessagingForbidden, notify

from .models import UserMute


def current_mute(user):
    """最新一条仍生效的禁言；顺带惰性解除已到期的。"""
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return None
    _expire_mutes(user)
    return _active_mute(user)


def is_muted(user) -> bool:
    return current_mute(user) is not None


def mute_user(actor, user, *, reason: str = "", ends_at=None) -> UserMute:
    if not actor.has_perm("reviews.mute_user"):
        raise MessagingForbidden("没有全站禁言权限")
    return _create_mute(actor, user, reason=reason, ends_at=ends_at)


def mute_user_for_report(actor, user, *, reason: str = "", ends_at=None) -> UserMute:
    """举报成立时的特权禁言（跳过权限检查）；仅 ``report_lifecycle`` 调用。"""
    return _create_mute(actor, user, reason=reason, ends_at=ends_at)


def lift_mute(actor, user) -> UserMute:
    if not actor.has_perm("reviews.mute_user"):
        raise MessagingForbidden("没有全站禁言权限")
    row = current_mute(user)
    if row is None:
        raise MessagingError("该用户未被禁言")
    row.lifted_at = timezone.now()
    row.save(update_fields=["lifted_at"])
    notify(user, "discipline", "mute_lifted", actor=actor, payload={"mute_id": row.pk})
    return row


# ---- 内部 ---------------------------------------------------------------

def _create_mute(actor, user, *, reason: str = "", ends_at=None) -> UserMute:
    if actor.pk == user.pk:
        raise MessagingError("不能禁言自己")
    # 审计 #277：处罚不能落在「权限不低于操作者」的账号上。原先唯一的防线是
    # 「不能禁言自己」，于是一个持 handle_report 的账号可以把超管和同级管理员
    # 全部禁言——举报成立链绕过 reviews.mute_user 之后就再没有别的闸门。
    if user.is_superuser:
        raise MessagingError("不能禁言超级管理员")
    if user.has_perm("reviews.handle_report"):
        raise MessagingError("不能处置持有举报处理权限的账号")
    if is_muted(user):
        raise MessagingError("该用户已被禁言")
    now = timezone.now()
    if ends_at is not None and ends_at <= now:
        raise MessagingError("结束时间须晚于当前时间")
    row = UserMute.objects.create(
        user=user, muted_by=actor, reason=reason or "", starts_at=now, ends_at=ends_at,
    )
    notify(user, "discipline", "muted", actor=actor, payload={
        "mute_id": row.pk,
        "reason": row.reason,
        "ends_at": ends_at.isoformat() if ends_at else None,
    })
    return row


def _active_mute(user, *, now=None) -> UserMute | None:
    now = now or timezone.now()
    return (
        UserMute.objects
        .filter(user=user, lifted_at__isnull=True)
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .order_by("-starts_at")
        .first()
    )


def _expire_mutes(user) -> None:
    now = timezone.now()
    expired = list(
        UserMute.objects.filter(
            user=user, lifted_at__isnull=True, ends_at__isnull=False, ends_at__lte=now,
        )
    )
    for row in expired:
        row.lifted_at = now
        row.save(update_fields=["lifted_at"])
        notify(user, "discipline", "mute_expired", actor=None, payload={"mute_id": row.pk})
