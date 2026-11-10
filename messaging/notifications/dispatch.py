"""分发流水线：业务事件 → 站内落库（按源的聚合键去重）+ 实时 push + 订阅匹配 → 外发通道投递（默认入队异步；`NOTIFICATIONS_DELIVERY_ASYNC=0` 回退同步）。"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import Notification, NotificationDelivery, NotificationSubscription
from .registry import all_channels, get_channel, get_source

logger = logging.getLogger(__name__)


def dispatch(
    source_key: str,
    event: str,
    recipients: Iterable,
    *,
    actor=None,
    payload: Mapping | None = None,
) -> list:
    """统一分发入口。

    - 站内：每条落库（Notification）并实时 push；用户可在订阅中关闭某源的站内
      （拒绝接收），关闭后该源对该用户整体静默（不落库、不推送、不外发）；
    - 聚合：源声明了 ``dedup_key``（见 ``NotificationSource.dedup_key``）时，收件人
      已有同键**未读**通知就不再新建，只把最新载荷并进既有那条（``payload.count``
      累加、``last_at`` 刷新）并再推一次；该通知被读掉之后，下一条同事项才重新通知。
      聚合命中的不重复外发（邮件等），避免「多一条消息就多一封邮件」；
    - 外发：按用户订阅（惰性默认）为启用的通道创建 NotificationDelivery 并入队，
      由进程内投递队列异步消费（失败按退避自动重试；见 notifications/queue.py 与 ADR-0024）；
      事务中调用时挂到提交后执行，避免「邮件已发、数据回滚」的幽灵通知。
      设 NOTIFICATIONS_DELIVERY_ASYNC=0 回退为提交后同步投递（失败仅留痕、不重试）。
    """
    source = get_source(source_key)
    if source is None:
        raise ValueError(f"未知通知源：{source_key}")
    data = dict(payload or {})
    if actor is not None:
        data.setdefault("actor_id", getattr(actor, "pk", None))
        data.setdefault("actor_username", getattr(actor, "username", ""))
    dedup_key = source.dedup_key(event, data)

    rows: list = []
    for user in recipients:
        if not site_enabled(user, source_key):
            continue  # 用户已拒绝接收该源的站内通知：整体静默
        row, created = _open_notification(user, source_key, event, data, dedup_key)
        _push(row)  # 聚合命中的也推一次：前端据此刷新列表与未读徽标
        if created:
            _deliver(row)
        rows.append(row)
    return rows


def _open_notification(
    user, source_key: str, event: str, data: Mapping, dedup_key: str,
) -> tuple[Notification, bool]:
    """在收件人处开一条未读通知；已有同聚合键的未读通知则并入。

    返回 ``(row, created)``——``created=False`` 表示并入了既有未读行。
    """
    if dedup_key:
        existing = _open_by_key(user, dedup_key)
        if existing is not None:
            _merge_into(existing, data)
            return existing, False
    try:
        # 保存点：并发下撞唯一约束时只回滚这一条 INSERT，不脏外层事务。
        with transaction.atomic():
            row = Notification.objects.create(
                recipient=user,
                category=source_key,
                event=event,
                payload=data,
                dedup_key=dedup_key,
            )
    except IntegrityError:
        row = _open_by_key(user, dedup_key) if dedup_key else None
        if row is None:  # pragma: no cover - 约束只在同键未读并发落库时命中
            raise
        _merge_into(row, data)
        return row, False
    return row, True


def _open_by_key(user, dedup_key: str):
    """该收件人同聚合键的未读通知（有则唯一/取最早一条）。"""
    return (
        Notification.objects
        .filter(recipient=user, dedup_key=dedup_key, read_at__isnull=True)
        .order_by("pk")
        .first()
    )


def _merge_into(row: Notification, data: Mapping) -> None:
    """把新载荷并进既有未读通知：字段以最新为准，``count`` 累加、``last_at`` 记录此刻。"""
    merged = dict(row.payload or {})
    merged.update(data)
    merged["count"] = int(merged.get("count") or 1) + 1
    merged["last_at"] = timezone.now().isoformat()
    row.payload = merged
    row.save(update_fields=["payload"])


def users_with_perm(perm: str) -> list:
    """持有 ``app_label.codename`` 权限的全部启用用户（直接授权 / 组授权 / 超级管理员）。

    权限驱动投递的收件人解析：动态查询、即时生效（刚获授权即收到、失去权限即停止）。
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    app_label, _, codename = perm.rpartition(".")
    if not app_label or not codename:
        raise ValueError(f"权限格式应为 app_label.codename：{perm!r}")
    User = get_user_model()
    return list(
        User.objects.filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(
                user_permissions__content_type__app_label=app_label,
                user_permissions__codename=codename,
            )
            | Q(
                groups__permissions__content_type__app_label=app_label,
                groups__permissions__codename=codename,
            )
        )
        .distinct()
    )


def all_active_users() -> list:
    """全部启用用户（全体广播类通知的收件人集）。"""
    from django.contrib.auth import get_user_model

    return list(get_user_model().objects.filter(is_active=True))


def site_enabled(user, source_key: str) -> bool:
    """该源是否对该用户开启站内（默认开启；用户可关闭以拒绝接收）。"""
    row = (
        NotificationSubscription.objects
        .filter(user=user, source_key=source_key, channel_key="site")
        .values_list("enabled", flat=True)
        .first()
    )
    return True if row is None else bool(row)


def subscribed_channels(user, source_key: str) -> list:
    """用户在某源上启用的通道列表（缺行回退到源定义 default_channels）。"""
    source = get_source(source_key)
    defaults = set(source.default_channels) if source else {"site"}
    rows = dict(
        NotificationSubscription.objects
        .filter(user=user, source_key=source_key)
        .values_list("channel_key", "enabled")
    )
    if not rows.get("site", True):
        return []  # 站内被关闭 = 拒绝接收：该源整体静默（与 dispatch 一致）
    result = []
    for channel in all_channels():
        enabled = rows.get(channel.key, channel.key in defaults)
        if enabled:
            result.append(channel.key)
    return result


def deliver(delivery: NotificationDelivery) -> bool:
    """同步投递单条投递行：成功标 sent，失败标 failed 留痕。本函数不抛出。"""
    channel = get_channel(delivery.channel_key)
    delivery.attempts = (delivery.attempts or 0) + 1
    if channel is None:
        delivery.status = NotificationDelivery.STATUS_FAILED
        delivery.last_error = f"未知通道：{delivery.channel_key}"
        delivery.save(update_fields=["status", "last_error", "attempts"])
        return False
    try:
        channel.deliver(delivery)
    except Exception as exc:
        delivery.status = NotificationDelivery.STATUS_FAILED
        delivery.last_error = str(exc)[:500]
        delivery.save(update_fields=["status", "last_error", "attempts"])
        logger.warning(
            "通知投递失败 delivery=%s channel=%s: %s",
            delivery.pk, delivery.channel_key, exc,
        )
        return False
    delivery.status = NotificationDelivery.STATUS_SENT
    delivery.sent_at = timezone.now()
    delivery.last_error = ""
    delivery.save(update_fields=["status", "sent_at", "last_error", "attempts"])
    return True


def _push(row: Notification) -> None:
    """实时推送（Channels 未接线时静默）。"""
    try:
        from ..services import push_user

        push_user(row.recipient_id, "notification", {
            "notification_id": row.pk,
            "category": row.category,
            "event": row.event,
        })
    except Exception:  # pragma: no cover - 推送失败不影响通知落库
        logger.debug("notification push failed id=%s", row.pk, exc_info=True)


def _deliver(row: Notification) -> None:
    """为启用的外发通道建投递行并同步投递（站内已落库，跳过）。"""
    for key in subscribed_channels(row.recipient, row.category):
        if key == "site":
            continue
        channel = get_channel(key)
        if channel is None:
            continue
        try:
            available = channel.is_available(row.recipient)
        except Exception:  # pragma: no cover - 防御性
            available = False
        if not available:
            continue
        delivery = NotificationDelivery.objects.create(
            notification=row,
            channel_key=key,
        )
        # 事务中调用时挂到提交后投递，避免「邮件已发、数据回滚」的幽灵通知。
        if getattr(settings, "NOTIFICATIONS_DELIVERY_ASYNC", False):
            # 异步（默认）：只入队——进程内队列 + 守护线程消费（notifications/queue.py）
            from .queue import enqueue

            transaction.on_commit(lambda d=delivery: enqueue(d.pk))
        else:
            # 同步（回退路径）：请求内投递，失败仅留痕、不重试
            transaction.on_commit(lambda d=delivery: deliver(d))
