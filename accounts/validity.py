"""账号身份有效期执行（ADR-0041）：管理员过期撤销、未认证超期停用。

惰性（登录 / 请求时）+ 定时（management command）共用本模块。规则：
- 超级管理员豁免（直接 no-op）。
- 管理员身份过期（委任通道 expires_at 已到）→ 撤销 ``is_staff``（触发 post_save 删除
  委任通道，回落普通用户，需重新授予）。
- 从未验证、注册超期（date_joined + 宽限，或 Profile.registration_deadline 覆盖）→
  停用账号（is_active=False）+ 标记 expiry_disabled_at（登录时给专属提示）。

幂等：已处理（is_active=False / is_staff=False）后重复调用为 no-op。
``dry_run=True`` 只返回将执行的动作、不落库（供 management command --dry-run）。
"""
from datetime import timedelta

from django.utils import timezone

from .identity_review import revoke_user_sessions
from .models import (
    Profile,
    Verification,
    has_ever_verified,
    profile_of,
    registration_verify_days,
)


def _registration_deadline(user, profile):
    """未认证账号的验证宽限截止：Profile 显式覆盖 > date_joined + 站点配置。"""
    if profile is not None and profile.registration_deadline is not None:
        return profile.registration_deadline
    return user.date_joined + timedelta(days=registration_verify_days())


def disable_user_for_expiry(user):
    """因超期未认证停用账号：is_active=False + 吊销会话 + 标记 expiry_disabled_at。"""
    now = timezone.now()
    if user.is_active:
        user.is_active = False
        user.save(update_fields=["is_active"])
        revoke_user_sessions(user)
    profile, _ = Profile.objects.get_or_create(user=user, defaults={"expiry_disabled_at": now})
    if profile.expiry_disabled_at is None:
        profile.expiry_disabled_at = now
        profile.save(update_fields=["expiry_disabled_at"])
    return user


def enforce_account_validity(user, dry_run=False):
    """执行一次身份有效期规则；返回动作名（admin_expired / unverified_expired）或 None。

    ``dry_run=True`` 只判定不落库。超管豁免；已停用账号不再处理（避免误改「手动停用」
    的提示语义）。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    # 超管豁免；已停用账号不再处理。
    if user.is_superuser or not user.is_active:
        return None
    now = timezone.now()

    # 1) 管理员身份过期 → 撤销 is_staff
    if user.is_staff:
        expired = user.verifications.filter(
            channel=Verification.CHANNEL_APPOINTMENT,
            status=Verification.STATUS_APPROVED,
            expires_at__isnull=False,
            expires_at__lte=now,
        ).exists()
        if expired:
            if not dry_run:
                user.is_staff = False
                user.save(update_fields=["is_staff"])  # post_save → 删除委任通道
            return "admin_expired"
        return None

    # 2) 从未验证、注册超期 → 停用
    if not has_ever_verified(user):
        profile = profile_of(user)
        if _registration_deadline(user, profile) <= now:
            if not dry_run:
                disable_user_for_expiry(user)
            return "unverified_expired"
    return None
