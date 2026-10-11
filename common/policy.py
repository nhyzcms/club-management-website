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


def _snapshot(row) -> SitePolicy:
    if row is None:
        return SitePolicy.defaults()
    return SitePolicy(
        verification_enabled=row.verification_enabled,
        content_review_enabled=row.content_review_enabled,
        registration_enabled=row.registration_enabled,
        register_per_ip_per_day=row.register_per_ip_per_day,
        resend_verification_per_ip_per_hour=row.resend_verification_per_ip_per_hour,
        login_per_ip_per_hour=row.login_per_ip_per_hour,
        login_per_username_per_hour=row.login_per_username_per_hour,
        feedback_anon_per_ip_per_day=row.feedback_anon_per_ip_per_day,
        reports_per_user_per_day=getattr(
            row, "reports_per_user_per_day", DEFAULT_REPORTS_PER_USER_PER_DAY,
        ),
        authcode_redeem_per_user_per_hour=getattr(
            row, "authcode_redeem_per_user_per_hour", DEFAULT_AUTHCODE_REDEEM_PER_USER_PER_HOUR,
        ),
        sync_upload_max_bytes=row.sync_upload_max_bytes,
        tus_media_max_bytes=row.tus_media_max_bytes,
        auto_update_enabled=row.auto_update_enabled,
        update_poll_interval_seconds=row.update_poll_interval_seconds,
        update_timezone=row.update_timezone,
        update_window_start_hour=row.update_window_start_hour,
        update_window_end_hour=row.update_window_end_hour,
        update_apply_cutoff_minutes_before_end=row.update_apply_cutoff_minutes_before_end,
        update_release_keep=row.update_release_keep,
        update_db_backup_keep=row.update_db_backup_keep,
        comments_enabled=row.comments_enabled,
        comment_max_depth=row.comment_max_depth,
        dms_enabled=row.dms_enabled,
        verification_valid_days=row.verification_valid_days,
        admin_valid_days=row.admin_valid_days,
        registration_verify_days=row.registration_verify_days,
    )


def get_policy() -> SitePolicy:
    """Return the cached site-policy snapshot (defaults if no row yet)."""
    cached = cache.get(CACHE_KEY)
    if isinstance(cached, SitePolicy):
        return cached
    from .models import SiteSettings

    try:
        row = SiteSettings.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        return SitePolicy.defaults()
    policy = _snapshot(row)
    cache.set(CACHE_KEY, policy, timeout=None)
    return policy


def invalidate_policy_cache() -> None:
    cache.delete(CACHE_KEY)
