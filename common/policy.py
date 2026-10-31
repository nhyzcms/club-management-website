"""Runtime site policy snapshot.

Operational knobs live in the ``SiteSettings`` singleton. Callers import
``get_policy()`` only — never query the model. Secrets / infra stay in
``config/settings.py`` + ``.env`` (ADR-0010).
"""
from __future__ import annotations

from dataclasses import dataclass

from django.core.cache import cache
from django.db.utils import OperationalError, ProgrammingError

CACHE_KEY = "common.site_policy"

# Defaults equal today's previously hardcoded values (behavior-neutral deploy).
DEFAULT_VERIFICATION_ENABLED = True
DEFAULT_CONTENT_REVIEW_ENABLED = True
DEFAULT_REGISTRATION_ENABLED = True
DEFAULT_REGISTER_PER_IP_PER_DAY = 5
DEFAULT_RESEND_VERIFICATION_PER_IP_PER_HOUR = 5
DEFAULT_LOGIN_PER_IP_PER_HOUR = 30
DEFAULT_LOGIN_PER_USERNAME_PER_HOUR = 10
DEFAULT_FEEDBACK_ANON_PER_IP_PER_DAY = 10
DEFAULT_REPORTS_PER_USER_PER_DAY = 10
DEFAULT_AUTHCODE_REDEEM_PER_USER_PER_HOUR = 10
# 社员身份编号（ADR-0025）：自助认领 / 扫码校验开关与限流。
DEFAULT_MEMBER_CLAIM_ENABLED = True
DEFAULT_MEMBER_CLAIM_PER_USER_PER_HOUR = 5
DEFAULT_MEMBER_CLAIM_PER_IP_PER_DAY = 20
DEFAULT_MEMBER_CHECK_PER_IP_PER_HOUR = 60
# 条码载荷查询（查询入口的 12 位签名路径）：现场一个人连扫几十上百张工牌，
# 60/时 会把操作者自己限流掉，所以单独一档、放宽到 300/时。
DEFAULT_MEMBER_LOOKUP_PER_IP_PER_HOUR = 300
# 安全验证（ADR-0026）：邮箱验证码每小时上限（按账号 / 按 IP）
DEFAULT_STEPUP_EMAIL_PER_USER_PER_HOUR = 5
DEFAULT_STEPUP_EMAIL_PER_IP_PER_HOUR = 10
DEFAULT_SYNC_UPLOAD_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_TUS_MEDIA_MAX_BYTES = 500 * 1024 * 1024
DEFAULT_AUTO_UPDATE_ENABLED = True
DEFAULT_UPDATE_POLL_INTERVAL_SECONDS = 900
DEFAULT_UPDATE_TIMEZONE = "Asia/Shanghai"
DEFAULT_UPDATE_WINDOW_START_HOUR = 1
DEFAULT_UPDATE_WINDOW_END_HOUR = 3
DEFAULT_UPDATE_APPLY_CUTOFF_MINUTES_BEFORE_END = 30
DEFAULT_UPDATE_RELEASE_KEEP = 3
DEFAULT_UPDATE_DB_BACKUP_KEEP = 5
DEFAULT_COMMENT_MAX_DEPTH = 8
DEFAULT_COMMENTS_ENABLED = True
DEFAULT_DMS_ENABLED = True
# 身份有效期（ADR-0041）：认证/管理员/注册宽限三档期限，天数可后台配置。
DEFAULT_VERIFICATION_VALID_DAYS = 365
DEFAULT_ADMIN_VALID_DAYS = 730
DEFAULT_REGISTRATION_VERIFY_DAYS = 60


@dataclass(frozen=True)
class SitePolicy:
    verification_enabled: bool
    content_review_enabled: bool
    registration_enabled: bool
    register_per_ip_per_day: int
    resend_verification_per_ip_per_hour: int
    login_per_ip_per_hour: int
    login_per_username_per_hour: int
    feedback_anon_per_ip_per_day: int
    reports_per_user_per_day: int
    authcode_redeem_per_user_per_hour: int
    member_claim_enabled: bool
    member_claim_per_user_per_hour: int
    member_claim_per_ip_per_day: int
    member_check_per_ip_per_hour: int
    member_lookup_per_ip_per_hour: int
    stepup_email_per_user_per_hour: int
    stepup_email_per_ip_per_hour: int
    sync_upload_max_bytes: int
    tus_media_max_bytes: int
    auto_update_enabled: bool
    update_poll_interval_seconds: int
    update_timezone: str
    update_window_start_hour: int
    update_window_end_hour: int
    update_apply_cutoff_minutes_before_end: int
    update_release_keep: int
    update_db_backup_keep: int
    comments_enabled: bool
    comment_max_depth: int
    dms_enabled: bool
    verification_valid_days: int
    admin_valid_days: int
    registration_verify_days: int

    @classmethod
    def defaults(cls) -> SitePolicy:
        return cls(
            verification_enabled=DEFAULT_VERIFICATION_ENABLED,
            content_review_enabled=DEFAULT_CONTENT_REVIEW_ENABLED,
            registration_enabled=DEFAULT_REGISTRATION_ENABLED,
            register_per_ip_per_day=DEFAULT_REGISTER_PER_IP_PER_DAY,
            resend_verification_per_ip_per_hour=DEFAULT_RESEND_VERIFICATION_PER_IP_PER_HOUR,
            login_per_ip_per_hour=DEFAULT_LOGIN_PER_IP_PER_HOUR,
            login_per_username_per_hour=DEFAULT_LOGIN_PER_USERNAME_PER_HOUR,
            feedback_anon_per_ip_per_day=DEFAULT_FEEDBACK_ANON_PER_IP_PER_DAY,
            reports_per_user_per_day=DEFAULT_REPORTS_PER_USER_PER_DAY,
            authcode_redeem_per_user_per_hour=DEFAULT_AUTHCODE_REDEEM_PER_USER_PER_HOUR,
            member_claim_enabled=DEFAULT_MEMBER_CLAIM_ENABLED,
            member_claim_per_user_per_hour=DEFAULT_MEMBER_CLAIM_PER_USER_PER_HOUR,
            member_claim_per_ip_per_day=DEFAULT_MEMBER_CLAIM_PER_IP_PER_DAY,
            member_check_per_ip_per_hour=DEFAULT_MEMBER_CHECK_PER_IP_PER_HOUR,
            member_lookup_per_ip_per_hour=DEFAULT_MEMBER_LOOKUP_PER_IP_PER_HOUR,
            stepup_email_per_user_per_hour=DEFAULT_STEPUP_EMAIL_PER_USER_PER_HOUR,
            stepup_email_per_ip_per_hour=DEFAULT_STEPUP_EMAIL_PER_IP_PER_HOUR,
            sync_upload_max_bytes=DEFAULT_SYNC_UPLOAD_MAX_BYTES,
            tus_media_max_bytes=DEFAULT_TUS_MEDIA_MAX_BYTES,
            auto_update_enabled=DEFAULT_AUTO_UPDATE_ENABLED,
            update_poll_interval_seconds=DEFAULT_UPDATE_POLL_INTERVAL_SECONDS,
            update_timezone=DEFAULT_UPDATE_TIMEZONE,
            update_window_start_hour=DEFAULT_UPDATE_WINDOW_START_HOUR,
            update_window_end_hour=DEFAULT_UPDATE_WINDOW_END_HOUR,
            update_apply_cutoff_minutes_before_end=DEFAULT_UPDATE_APPLY_CUTOFF_MINUTES_BEFORE_END,
            update_release_keep=DEFAULT_UPDATE_RELEASE_KEEP,
            update_db_backup_keep=DEFAULT_UPDATE_DB_BACKUP_KEEP,
            comments_enabled=DEFAULT_COMMENTS_ENABLED,
            comment_max_depth=DEFAULT_COMMENT_MAX_DEPTH,
            dms_enabled=DEFAULT_DMS_ENABLED,
            verification_valid_days=DEFAULT_VERIFICATION_VALID_DAYS,
            admin_valid_days=DEFAULT_ADMIN_VALID_DAYS,
            registration_verify_days=DEFAULT_REGISTRATION_VERIFY_DAYS,
        )


def format_byte_cap(n: int) -> str:
    """Human label for an upload cap (e.g. ``50MB``) used in error text."""
    if n >= 1024 * 1024 and n % (1024 * 1024) == 0:
        return f"{n // (1024 * 1024)}MB"
    if n >= 1024 and n % 1024 == 0:
        return f"{n // 1024}KB"
    return f"{n} 字节"


def _snapshot(rows) -> SitePolicy:
    """把五张策略表的行组装成一个 ``SitePolicy``。

    ``rows`` 是 ``{"auth": ..., "rate": ..., "upload": ..., "updater": ..., "content": ...}``，
    任一项可以是 ``None``（表里还没建行 / 迁移未跑）——那时用该字段的默认值，
    而不是整份回落 defaults。这样「只配了频控、没配上传」也能正常工作。
    """
    auth = rows.get("auth")
    rate = rows.get("rate")
    upload = rows.get("upload")
    updater = rows.get("updater")
    content = rows.get("content")

    def pick(row, name, default):
        return getattr(row, name, default) if row is not None else default

    return SitePolicy(
        verification_enabled=pick(
            auth, "verification_enabled", DEFAULT_VERIFICATION_ENABLED,
        ),
        content_review_enabled=pick(
            content, "content_review_enabled", DEFAULT_CONTENT_REVIEW_ENABLED,
        ),
        registration_enabled=pick(
            auth, "registration_enabled", DEFAULT_REGISTRATION_ENABLED,
        ),
        register_per_ip_per_day=pick(
            rate, "register_per_ip_per_day", DEFAULT_REGISTER_PER_IP_PER_DAY,
        ),
        resend_verification_per_ip_per_hour=pick(
            rate, "resend_verification_per_ip_per_hour",
            DEFAULT_RESEND_VERIFICATION_PER_IP_PER_HOUR,
        ),
        login_per_ip_per_hour=pick(
            rate, "login_per_ip_per_hour", DEFAULT_LOGIN_PER_IP_PER_HOUR,
        ),
        login_per_username_per_hour=pick(
            rate, "login_per_username_per_hour", DEFAULT_LOGIN_PER_USERNAME_PER_HOUR,
        ),
        feedback_anon_per_ip_per_day=pick(
            rate, "feedback_anon_per_ip_per_day", DEFAULT_FEEDBACK_ANON_PER_IP_PER_DAY,
        ),
        reports_per_user_per_day=pick(
            rate, "reports_per_user_per_day", DEFAULT_REPORTS_PER_USER_PER_DAY,
        ),
        authcode_redeem_per_user_per_hour=pick(
            rate, "authcode_redeem_per_user_per_hour",
            DEFAULT_AUTHCODE_REDEEM_PER_USER_PER_HOUR,
        ),
        member_claim_enabled=pick(
            auth, "member_claim_enabled", DEFAULT_MEMBER_CLAIM_ENABLED,
        ),
        member_claim_per_user_per_hour=pick(
            rate, "member_claim_per_user_per_hour",
            DEFAULT_MEMBER_CLAIM_PER_USER_PER_HOUR,
        ),
        member_claim_per_ip_per_day=pick(
            rate, "member_claim_per_ip_per_day", DEFAULT_MEMBER_CLAIM_PER_IP_PER_DAY,
        ),
        member_check_per_ip_per_hour=pick(
            rate, "member_check_per_ip_per_hour", DEFAULT_MEMBER_CHECK_PER_IP_PER_HOUR,
        ),
        member_lookup_per_ip_per_hour=pick(
            rate, "member_lookup_per_ip_per_hour", DEFAULT_MEMBER_LOOKUP_PER_IP_PER_HOUR,
        ),
        stepup_email_per_user_per_hour=pick(
            rate, "stepup_email_per_user_per_hour", DEFAULT_STEPUP_EMAIL_PER_USER_PER_HOUR,
        ),
        stepup_email_per_ip_per_hour=pick(
            rate, "stepup_email_per_ip_per_hour", DEFAULT_STEPUP_EMAIL_PER_IP_PER_HOUR,
        ),
        sync_upload_max_bytes=pick(
            upload, "sync_upload_max_bytes", DEFAULT_SYNC_UPLOAD_MAX_BYTES,
        ),
        tus_media_max_bytes=pick(
            upload, "tus_media_max_bytes", DEFAULT_TUS_MEDIA_MAX_BYTES,
        ),
        auto_update_enabled=pick(
            updater, "auto_update_enabled", DEFAULT_AUTO_UPDATE_ENABLED,
        ),
        update_poll_interval_seconds=pick(
            updater, "update_poll_interval_seconds", DEFAULT_UPDATE_POLL_INTERVAL_SECONDS,
        ),
        update_timezone=pick(updater, "update_timezone", DEFAULT_UPDATE_TIMEZONE),
        update_window_start_hour=pick(
            updater, "update_window_start_hour", DEFAULT_UPDATE_WINDOW_START_HOUR,
        ),
        update_window_end_hour=pick(
            updater, "update_window_end_hour", DEFAULT_UPDATE_WINDOW_END_HOUR,
        ),
        update_apply_cutoff_minutes_before_end=pick(
            updater, "update_apply_cutoff_minutes_before_end",
            DEFAULT_UPDATE_APPLY_CUTOFF_MINUTES_BEFORE_END,
        ),
        update_release_keep=pick(
            updater, "update_release_keep", DEFAULT_UPDATE_RELEASE_KEEP,
        ),
        update_db_backup_keep=pick(
            updater, "update_db_backup_keep", DEFAULT_UPDATE_DB_BACKUP_KEEP,
        ),
        comments_enabled=pick(content, "comments_enabled", DEFAULT_COMMENTS_ENABLED),
        comment_max_depth=pick(content, "comment_max_depth", DEFAULT_COMMENT_MAX_DEPTH),
        dms_enabled=pick(content, "dms_enabled", DEFAULT_DMS_ENABLED),
        verification_valid_days=pick(
            auth, "verification_valid_days", DEFAULT_VERIFICATION_VALID_DAYS,
        ),
        admin_valid_days=pick(auth, "admin_valid_days", DEFAULT_ADMIN_VALID_DAYS),
        registration_verify_days=pick(
            auth, "registration_verify_days", DEFAULT_REGISTRATION_VERIFY_DAYS,
        ),
    )


def get_policy() -> SitePolicy:
    """Return the cached site-policy snapshot.

    五张表各读一行（都按 pk=1）。表里没行时该领域回落默认值，不是整份回落——
    「只配了频控、没配上传」是合法状态。
    """
    cached = cache.get(CACHE_KEY)
    if isinstance(cached, SitePolicy):
        return cached
    from .models import (
        AuthPolicy,
        ContentPolicy,
        RateLimitPolicy,
        UpdaterPolicy,
        UploadPolicy,
    )

    try:
        rows = {
            "auth": AuthPolicy.objects.filter(pk=1).first(),
            "rate": RateLimitPolicy.objects.filter(pk=1).first(),
            "upload": UploadPolicy.objects.filter(pk=1).first(),
            "updater": UpdaterPolicy.objects.filter(pk=1).first(),
            "content": ContentPolicy.objects.filter(pk=1).first(),
        }
    except (OperationalError, ProgrammingError):
        return SitePolicy.defaults()
    policy = _snapshot(rows)
    cache.set(CACHE_KEY, policy, timeout=None)
    return policy


def invalidate_policy_cache() -> None:
    cache.delete(CACHE_KEY)
