"""B5 之后的策略测试夹具。

## 为什么需要

``SiteSettings`` 已拆成五张领域表，``get_policy()`` 只读新表。测试里原来那句

```python
SiteSettings(comment_max_depth=1).save()
```

现在**不会影响 get_policy()**——它写的是没人读的旧表，测试会静默通过错误的断言
（或者莫名其妙地失败）。

``set_policy(**fields)`` 按字段名找到所属的新表，写进去，再清缓存。

## 为什么按字段名查表，而不是让调用方指定模型

测试关心的是「把 comment_max_depth 设成 1」，不关心它住在哪张表。让调用方记
五个模型名是把这个重构的细节泄漏到 36 个测试里。字段名 → 模型是这张表唯一
需要维护的地方。
"""
from collections import defaultdict

from .models import (
    AuthPolicy,
    ContentPolicy,
    RateLimitPolicy,
    UpdaterPolicy,
    UploadPolicy,
)
from .policy import invalidate_policy_cache

POLICY_MODEL_OF = {
    # AuthPolicy
    "verification_enabled": AuthPolicy,
    "verification_valid_days": AuthPolicy,
    "admin_valid_days": AuthPolicy,
    "registration_verify_days": AuthPolicy,
    "registration_enabled": AuthPolicy,
    "member_claim_enabled": AuthPolicy,
    # RateLimitPolicy
    "register_per_ip_per_day": RateLimitPolicy,
    "resend_verification_per_ip_per_hour": RateLimitPolicy,
    "login_per_ip_per_hour": RateLimitPolicy,
    "login_per_username_per_hour": RateLimitPolicy,
    "feedback_anon_per_ip_per_day": RateLimitPolicy,
    "reports_per_user_per_day": RateLimitPolicy,
    "authcode_redeem_per_user_per_hour": RateLimitPolicy,
    "member_claim_per_user_per_hour": RateLimitPolicy,
    "member_claim_per_ip_per_day": RateLimitPolicy,
    "member_check_per_ip_per_hour": RateLimitPolicy,
    "member_lookup_per_ip_per_hour": RateLimitPolicy,
    "stepup_email_per_user_per_hour": RateLimitPolicy,
    "stepup_email_per_ip_per_hour": RateLimitPolicy,
    # UploadPolicy
    "sync_upload_max_bytes": UploadPolicy,
    "tus_media_max_bytes": UploadPolicy,
    # UpdaterPolicy
    "auto_update_enabled": UpdaterPolicy,
    "update_poll_interval_seconds": UpdaterPolicy,
    "update_timezone": UpdaterPolicy,
    "update_window_start_hour": UpdaterPolicy,
    "update_window_end_hour": UpdaterPolicy,
    "update_apply_cutoff_minutes_before_end": UpdaterPolicy,
    "update_release_keep": UpdaterPolicy,
    "update_db_backup_keep": UpdaterPolicy,
    # ContentPolicy
    "content_review_enabled": ContentPolicy,
    "comments_enabled": ContentPolicy,
    "comment_max_depth": ContentPolicy,
    "dms_enabled": ContentPolicy,
}


def set_policy(**fields):
    """把策略字段写进对应的新表并清缓存。

    未知字段直接抛 ``TypeError``——静默忽略会让测试以为设了值其实没设，
    那类失败最难查（断言对，但前置条件没生效）。
    """
    unknown = set(fields) - set(POLICY_MODEL_OF)
    if unknown:
        raise TypeError(f"set_policy 不认识这些字段：{sorted(unknown)}")

    grouped: dict[type, dict] = defaultdict(dict)
    for name, value in fields.items():
        grouped[POLICY_MODEL_OF[name]][name] = value

    for model, values in grouped.items():
        row, _ = model.objects.get_or_create(pk=1)
        for name, value in values.items():
            setattr(row, name, value)
        row.save(update_fields=list(values))

    invalidate_policy_cache()
