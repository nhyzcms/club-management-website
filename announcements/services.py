"""全站弹窗公告的领域逻辑：受众解析、发布（弹窗 + 站内通知 + 可选邮件）、已读台账。

与相邻模块的分工：

- ``messaging.notifications``：通知框架（源 × 通道 × 订阅 + 异步投递队列）。本模块只负责
  「发给谁、发什么」，落库 / 推送 / 邮件重试全部复用 ``notify_many`` 与 ``NotificationDelivery``；
- ``accounts.models``：``is_verified`` / ``admin_identity_valid`` 是身份判定的唯一真源，
  本模块的受众 SQL 与这两个函数**逐条等价**（同一套 status + 有效期条件），不另立口径。
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Verification, admin_identity_valid, is_verified
from messaging.models import NotificationDelivery
from messaging.services import notify_many

from .models import Announcement, AnnouncementRead

AUDIENCE_ALL = Announcement.AUDIENCE_ALL
AUDIENCE_REGISTERED = Announcement.AUDIENCE_REGISTERED
AUDIENCE_VERIFIED = Announcement.AUDIENCE_VERIFIED
AUDIENCE_ADMIN = Announcement.AUDIENCE_ADMIN

AUDIENCE_LABELS = dict(Announcement.AUDIENCE_CHOICES)

# 弹窗一次最多返回几条（正常情况下前端一条一条弹，读完再弹下一条）。
ACTIVE_LIMIT = 5
# 邮件正文里引用的正文摘要长度（完整内容要点进站内看）。
EMAIL_SUMMARY_CHARS = 300


# ---- 受众 ---------------------------------------------------------------

def _channel_unexpired_q():
    """``accounts.models._unexpired_filter()`` 的**关联字段版**（同语义、带 verifications__ 前缀）。

    不能直接复用后者：它写的是 ``expires_at``，在 User 查询里会被解析成 User 自己的字段
    （不存在）。两边条件必须保持一致：``expires_at`` 为空 = 永久有效。
    """
    now = timezone.now()
    return (
        Q(verifications__expires_at__isnull=True)
        | Q(verifications__expires_at__gt=now)
    )


def recipient_queryset(audience: str):
    """该受众的启用账号集（与 ``is_verified`` / ``admin_identity_valid`` 同口径）。"""
    User = get_user_model()
    users = User.objects.filter(is_active=True)
    if audience == AUDIENCE_REGISTERED:
        return users
    if audience == AUDIENCE_VERIFIED:
        # 注意：条件必须写在**同一个 filter()** 里——Django 会在同一次 filter 内复用同一个
        # 关联 join，语义才是「存在一行：approved 且未过期」。拆成两次 filter 会产生两个
        # join，可能被「一行已过期 + 另一行未过期」凑成假阳性。
        return users.filter(
            Q(verifications__status=Verification.STATUS_APPROVED)
            & _channel_unexpired_q(),
        ).distinct()
    if audience == AUDIENCE_ADMIN:
        appointed = (
            Q(
                verifications__channel=Verification.CHANNEL_APPOINTMENT,
                verifications__status=Verification.STATUS_APPROVED,
            )
            & _channel_unexpired_q()
        )
        return users.filter(Q(is_superuser=True) | (Q(is_staff=True) & appointed)).distinct()
    # AUDIENCE_ALL：登录与否都能看见，但「推送到站内」只对已有账号有意义。
    return users


def recipient_count(audience: str) -> int:
    return recipient_queryset(audience).count()


def audience_matches(user, audience: str) -> bool:
    """单个用户是否在该受众内（弹窗可见性判定；匿名只匹配「全站」）。"""
    if audience == AUDIENCE_ALL:
        return True
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if audience == AUDIENCE_REGISTERED:
        return True
    if audience == AUDIENCE_VERIFIED:
        return bool(is_verified(user))
    if audience == AUDIENCE_ADMIN:
        return bool(user.is_superuser or admin_identity_valid(user))
    return False


# ---- 可见性 -------------------------------------------------------------

def can_see(user, announcement: Announcement, now=None) -> bool:
    """能否看到这条公告：必须「在线」（已发布 + 未过下线时间）且在受众内。"""
    if announcement is None or not announcement.is_live(now):
        return False
    return audience_matches(user, announcement.audience)


def active_for(user, now=None, limit: int = ACTIVE_LIMIT) -> list[Announcement]:
    """当前用户还没读过的在线公告（按发布时间正序，先发的先弹）。"""
    now = now or timezone.now()
    rows = [
        row
        for row in Announcement.objects.filter(status=Announcement.STATUS_PUBLISHED)
        .order_by("published_at", "pk")
        if row.is_live(now) and audience_matches(user, row.audience)
    ]
    if getattr(user, "is_authenticated", False):
        read_ids = set(
            AnnouncementRead.objects
            .filter(user=user, announcement__in=rows)
            .values_list("announcement_id", flat=True)
        )
        rows = [row for row in rows if row.pk not in read_ids]
    return rows[:limit]


# ---- 发布 ---------------------------------------------------------------

def publish(announcement: Announcement, actor=None, now=None) -> dict:
    """发布：置状态 + 站内通知全体受众 +（可选）邮件。

    幂等：已经发布过（``published_at`` 非空）的公告再次调用不会重复推送，只返回
    ``{"already_published": True}``——后台「保存并继续编辑」不会给全员发第二遍。
    """
    now = now or timezone.now()
    if announcement.published_at is not None:
        return {"already_published": True, "recipients": 0, "notified": 0, "emails": 0}

    with transaction.atomic():
        announcement.status = Announcement.STATUS_PUBLISHED
        announcement.published_at = now
        announcement.save(update_fields=["status", "published_at", "updated_at"])

        users = list(recipient_queryset(announcement.audience))
        payload = {
            "announcement_id": announcement.pk,
            "title": announcement.title,
            "url": f"/announcements/{announcement.pk}",
            "audience": announcement.audience,
            "file_kind": announcement.document_kind,
            "summary": (announcement.summary or "")[:EMAIL_SUMMARY_CHARS],
        }
        rows = notify_many(
            users, "announcement", "published", actor=actor, payload=payload,
        )
        emails = _send_emails(rows) if announcement.send_email else 0

    return {
        "already_published": False,
        "recipients": len(users),
        "notified": len(rows),
        "emails": emails,
    }


def _send_emails(rows) -> int:
    """为每条站内通知补一条邮件投递（只发给已认证邮箱；走投递队列，可重试）。"""
    from messaging.notifications import get_channel

    channel = get_channel("email")
    if channel is None:  # pragma: no cover - 邮件通道是内置的
        return 0
    queued = 0
    for row in rows:
        try:
            available = channel.is_available(row.recipient)
        except Exception:  # pragma: no cover - 防御性
            available = False
        if not available:
            continue
        delivery = NotificationDelivery.objects.create(
            notification=row, channel_key="email",
        )
        queued += 1
        if getattr(settings, "NOTIFICATIONS_DELIVERY_ASYNC", False):
            from messaging.notifications.queue import enqueue

            transaction.on_commit(lambda d=delivery: enqueue(d.pk))
        else:
            from messaging.notifications.dispatch import deliver

            transaction.on_commit(lambda d=delivery: deliver(d))
    return queued


def unpublish(announcement: Announcement) -> None:
    """下线：停止弹窗，站内通知保留（收件人仍可回看）。"""
    announcement.status = Announcement.STATUS_ARCHIVED
    announcement.save(update_fields=["status", "updated_at"])


# ---- 已读 ---------------------------------------------------------------

def mark_read(announcement: Announcement, user) -> tuple[AnnouncementRead, bool]:
    """记已读（幂等）。返回 ``(row, created)``。"""
    row, created = AnnouncementRead.objects.get_or_create(
        announcement=announcement, user=user,
    )
    return row, created


def read_map(announcement: Announcement) -> dict[int, object]:
    """``{user_id: read_at}``（后台已读明细与序列化复用）。"""
    return dict(
        announcement.reads.values_list("user_id", "read_at")
    )


def stats(announcement: Announcement) -> dict:
    """后台统计：受众规模 / 已读人数 / 阅读率 / 邮件投递数。"""
    recipients = recipient_count(announcement.audience)
    read_count = announcement.reads.count()
    emails = NotificationDelivery.objects.filter(
        notification__category="announcement",
        notification__payload__announcement_id=announcement.pk,
        channel_key="email",
    ).count()
    emails_sent = NotificationDelivery.objects.filter(
        notification__category="announcement",
        notification__payload__announcement_id=announcement.pk,
        channel_key="email",
        status=NotificationDelivery.STATUS_SENT,
    ).count()
    return {
        "recipients": recipients,
        "read_count": read_count,
        "unread_count": max(recipients - read_count, 0),
        "read_rate": round(read_count * 100 / recipients, 1) if recipients else 0.0,
        "email_queued": emails,
        "email_sent": emails_sent,
    }
