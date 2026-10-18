"""评论区 / 私信 / 通知 / 禁言 / 横幅 — 其它 app 只碰本模块，不 import 模型或 viewset。

写入规则（认证门禁、全站禁言、评论区状态、嵌套上限、3 分钟撤回、墓碑删除）都收在这里。
HTTP 是事实源；``push_user`` / ``push_thread`` 只是推送适配器（Channels 未接线时静默 no-op）。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from common.policy import get_policy
from reviews.visibility import visible_queryset

from .models import (
    Banner,
    Comment,
    CommentThread,
    Conversation,
    Message,
    MessageReadStatus,
    Notification,
)

logger = logging.getLogger(__name__)

RETRACT_WINDOW = timedelta(minutes=3)
MENTION_RE = re.compile(r"@(\w+)")


class MessagingError(Exception):
    """领域规则失败。视图映射 ``status`` → HTTP。"""

    status = 400

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class MessagingForbidden(MessagingError):
    status = 403


class MessagingNotFound(MessagingError):
    status = 404


# ---- 宿主 / 评论区 -------------------------------------------------------

def host_of(thread: CommentThread):
    if thread.news_id:
        return thread.news
    if thread.activity_id:
        return thread.activity
    if thread.task_id:
        return thread.task
    raise MessagingError("评论区没有宿主")


def thread_for(host) -> CommentThread:
    """取或建该宿主上恰好一条评论区（默认开放）。"""
    field = host._meta.model_name
    if field not in ("news", "activity", "task"):
        raise MessagingError("评论区只能挂在新闻、活动或任务上")
    thread, _created = CommentThread.objects.get_or_create(
        **{field: host},
        defaults={"status": CommentThread.STATUS_OPEN},
    )
    return thread


def can_see_host(user, host) -> bool:
    """谁能看见宿主，谁就能看见其评论区（未公开的新闻评论区不对公众开放）。"""
    name = host._meta.model_name
    authenticated = bool(user and getattr(user, "is_authenticated", False))
    if name == "news":
        from news.models import News

        qs = News.objects.filter(pk=host.pk)
        visible = visible_queryset(qs, user, "news", action="retrieve")
        if not authenticated:
            return visible.filter(is_published=True).exists()
        if user.has_perm("reviews.moderate"):
            return visible.exists()
        return visible.filter(Q(is_published=True) | Q(author=user)).exists()
    if name == "activity":
        from activities.models import Activity

        qs = Activity.objects.filter(pk=host.pk)
        if not authenticated:
            return visible_queryset(qs, user, "activity", action="list").filter(
                type="survey", audience="public",
            ).exists()
        return visible_queryset(qs, user, "activity", action="retrieve").exists()
    if name == "task":
        return authenticated
    return False


def can_manage_thread(user, thread: CommentThread) -> bool:
    """改评论区状态 / 墓碑删评论：宿主主人（所有权）**或** ``messaging.manage_comment_thread``。

    不继承「管理新闻 / 活动 / 任务」——发稿和管评论是两条权限，组策略分开授。
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.has_perm("messaging.manage_comment_thread"):
        return True
    host = host_of(thread)
    owner_id = _host_owner_id(host)
    return owner_id is not None and owner_id == user.pk


def can_see_thread(user, thread: CommentThread) -> bool:
    """彻底关闭后普通读者看不到该区；协管仍可看。"""
    if not can_see_host(user, host_of(thread)):
        return False
    if thread.status == CommentThread.STATUS_CLOSED:
        return can_manage_thread(user, thread)
    return True


def set_thread_status(thread: CommentThread, user, status: str) -> CommentThread:
    if not can_manage_thread(user, thread):
        raise MessagingForbidden("没有管理该评论区的权限")
    allowed = {
        CommentThread.STATUS_OPEN,
        CommentThread.STATUS_MUTED,
        CommentThread.STATUS_CLOSED,
    }
    if status not in allowed:
        raise MessagingError("状态须为 open、muted 或 closed")
    thread.status = status
    thread.save(update_fields=["status"])
    return thread


def post_comment(thread: CommentThread, author, content: str, *, parent: Comment | None = None) -> Comment:
    content = (content or "").strip()
    if not content:
        raise MessagingError("评论内容不能为空")
    if not can_see_thread(author, thread):
        raise MessagingNotFound("评论区不存在")
    if thread.status == CommentThread.STATUS_MUTED:
        raise MessagingError("评论区已禁言")
    if thread.status != CommentThread.STATUS_OPEN:
        raise MessagingError("评论区已关闭")
    if is_muted(author):
        raise MessagingForbidden("你已被全站禁言，暂时不能发言")
    if parent is not None:
        if parent.thread_id != thread.pk:
            raise MessagingError("父评论不属于该评论区")
        depth = _depth(parent) + 1
    else:
        depth = 1
    cap = get_policy().comment_max_depth
    if depth > cap:
        raise MessagingError("超过最大嵌套层数")

    comment = Comment.objects.create(
        thread=thread, author=author, parent=parent, content=content,
    )
    push_thread(thread.pk, "comment", {
        "thread_id": thread.pk, "comment_id": comment.pk,
    })
    _notify_comment(comment, author, parent)
    return comment


def retract_comment(comment: Comment, user) -> Comment:
    if comment.author_id != user.pk:
        raise MessagingForbidden("只能撤回自己的评论")
    if comment.deleted_at:
        raise MessagingError("评论已删除")
    if comment.retracted_at:
        raise MessagingError("评论已撤回")
    if comment.replies.exists():
        raise MessagingError("已有回复，不能撤回")
    if timezone.now() - comment.created_at > RETRACT_WINDOW:
        raise MessagingError("已超过撤回时限")
    comment.retracted_at = timezone.now()
    comment.save(update_fields=["retracted_at", "updated_at"])
    push_thread(comment.thread_id, "comment", {
        "thread_id": comment.thread_id, "comment_id": comment.pk, "retracted": True,
    })
    return comment


def delete_comment(comment: Comment, user) -> Comment:
    if not can_manage_thread(user, comment.thread):
        raise MessagingForbidden("没有管理该评论区的权限")
    if comment.deleted_at:
        raise MessagingError("评论已删除")
    return _tombstone_comment(comment, user)


def delete_comment_for_report(comment: Comment, user) -> Comment:
    """举报成立时的特权墓碑：跳过 ``can_manage_thread``。仅 ``report_lifecycle`` 可调用。

    已删除则幂等返回。
    """
    if comment.deleted_at:
        return comment
    return _tombstone_comment(comment, user)


def _tombstone_comment(comment: Comment, user) -> Comment:
    comment.deleted_at = timezone.now()
    comment.deleted_by = user
    comment.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
    push_thread(comment.thread_id, "comment", {
        "thread_id": comment.thread_id, "comment_id": comment.pk, "deleted": True,
    })
    return comment


# ---- 全站禁言 ------------------------------------------------------------

# ---- 禁言（已迁至 reviews.discipline；以下为兼容转发，Deprecated）-----------

def current_mute(user):
    """Deprecated: 请改用 ``reviews.discipline.current_mute``。"""
    from reviews.discipline import current_mute as _impl

    return _impl(user)


def is_muted(user) -> bool:
    """Deprecated: 请改用 ``reviews.discipline.is_muted``。"""
    from reviews.discipline import is_muted as _impl

    return _impl(user)


def mute_user(actor, user, *, reason: str = "", ends_at=None):
    """Deprecated: 请改用 ``reviews.discipline.mute_user``。"""
    from reviews.discipline import mute_user as _impl

    return _impl(actor, user, reason=reason, ends_at=ends_at)


def mute_user_for_report(actor, user, *, reason: str = "", ends_at=None):
    """Deprecated: 请改用 ``reviews.discipline.mute_user_for_report``。"""
    from reviews.discipline import mute_user_for_report as _impl

    return _impl(actor, user, reason=reason, ends_at=ends_at)


def lift_mute(actor, user):
    """Deprecated: 请改用 ``reviews.discipline.lift_mute``。"""
    from reviews.discipline import lift_mute as _impl

    return _impl(actor, user)


# ---- 通知 / 横幅 / 推送 ---------------------------------------------------

def notify(
    recipient, category: str, event: str, *, actor=None, payload: Mapping | None = None,
) -> Notification | None:
    """兼容薄封装 → 通知框架（站内落库 + 推送 + 外发通道按订阅同步投递）。

    详见 ``messaging.notifications.dispatch``；邮件等外发同步发送，失败仅留痕
    （NotificationDelivery），不自动重试。用户关闭该源的站内通道（拒绝接收）时
    整条静默并返回 None。源声明了聚合键时，收件人已有同键未读通知则并入那条并
    返回它（不重复外发）——「同一未读事项只通知一次」见 ``NotificationSource``。
    """
    from .notifications.dispatch import dispatch

    try:
        rows = dispatch(category, event, [recipient], actor=actor, payload=payload)
    except ValueError as exc:
        raise MessagingError(str(exc)) from exc
    return rows[0] if rows else None


def notify_many(
    recipients, category: str, event: str, *, actor=None, payload: Mapping | None = None,
) -> list:
    """向多收件人投递同一事件（自动去重、跳过 None）。返回落库的通知列表。"""
    from .notifications.dispatch import dispatch

    seen: set = set()
    users = []
    for user in recipients:
        if user is None or user.pk in seen:
            continue
        seen.add(user.pk)
        users.append(user)
    if not users:
        return []
    try:
        return dispatch(category, event, users, actor=actor, payload=payload)
    except ValueError as exc:
        raise MessagingError(str(exc)) from exc


def notify_all(
    category: str, event: str, *, actor=None, payload: Mapping | None = None,
) -> list:
    """全站广播：向所有启用用户投递（订阅开关与静默规则照常生效）。"""
    from .notifications.dispatch import all_active_users

    return notify_many(all_active_users(), category, event, actor=actor, payload=payload)


def notify_perm(
    category: str, event: str, perm: str, *,
    actor=None, payload: Mapping | None = None, extra_recipients=(),
) -> list:
    """权限驱动投递：收件人 = 持有 ``perm``（``app_label.codename``）的全部用户。

    - 动态解析：直接授权 / 组授权 / 超级管理员（刚获权即收、失权即停）
    - 自动去重，并排除操作者本人（自己提交/操作不必再通知自己）
    """
    from .notifications.dispatch import users_with_perm

    recipients = users_with_perm(perm) + list(extra_recipients)
    if actor is not None:
        recipients = [u for u in recipients if u.pk != actor.pk]
    return notify_many(recipients, category, event, actor=actor, payload=payload)


def current_banner(now=None) -> Banner | None:
    """当前窗口内至多一条：priority 高者胜，并列取较新。"""
    now = now or timezone.now()
    return (
        Banner.objects
        .filter(starts_at__lte=now, ends_at__gt=now)
        .order_by("-priority", "-created_at")
        .first()
    )


def push_user(user_id, event: str, payload: Mapping | None = None) -> None:
    _group_send(f"user_{user_id}", event, payload)


def push_thread(thread_id, event: str, payload: Mapping | None = None) -> None:
    _group_send(f"thread_{thread_id}", event, payload)


# ---- 私信（1:1） ---------------------------------------------------------

def start_private(user, target) -> tuple[Conversation, bool]:
    """返回 ``(conversation, created)``。"""
    if target.pk == user.pk:
        raise MessagingError("不能和自己对话")
    from accounts.models import is_deleted_user, is_verified

    if is_deleted_user(target):
        raise MessagingForbidden("该用户已注销，无法发起私信")
    if not is_verified(target):
        raise MessagingError("对方尚未完成认证")
    if is_muted(user):
        raise MessagingForbidden("你已被全站禁言，暂时不能发言")
    existing = (
        Conversation.objects
        .filter(participants=user)
        .filter(participants=target)
        .first()
    )
    if existing:
        return existing, False
    conversation = Conversation.objects.create()
    conversation.participants.set([user, target])
    return conversation, True


def send_dm(conversation: Conversation, sender, content: str) -> Message:
    content = (content or "").strip()
    if not content:
        raise MessagingError("消息内容不能为空")
    if not conversation.participants.filter(pk=sender.pk).exists():
        raise MessagingForbidden("不是该会话的参与者")
    if conversation.participants.filter(profile__deleted_at__isnull=False).exclude(pk=sender.pk).exists():
        # 对方已注销：历史消息可读，但不能继续发（ADR-0025）。
        raise MessagingForbidden("该用户已注销，无法继续发送私信")
    if is_muted(sender):
        raise MessagingForbidden("你已被全站禁言，暂时不能发言")
    message = Message.objects.create(
        conversation=conversation, sender=sender, content=content,
    )
    mentioned = _mentioned_users(content)
    if mentioned:
        message.mentions.set(mentioned)
    Conversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
    others = list(conversation.participants.exclude(pk=sender.pk))
    for other in others:
        push_user(other.pk, "dm", {
            "conversation_id": conversation.pk, "message_id": message.pk,
        })
    notify_many(
        others,
        "dm",
        "new_message",
        actor=sender,
        payload={
            "type": "dm",
            "id": conversation.pk,
            "title": getattr(conversation, "title", "") or "",
            "url": f"/messages/{conversation.pk}",
        },
    )
    return message


def mark_conversation_read(user, conversation) -> int:
    """把会话中他人发来的消息标为已读；并联动把该会话的未读站内通知标为已读。

    返回本次**新**标记的消息数。「读私信 ⇒ 通知也已读」是产品规则：不论是从通知
    入口点进来读的，还是直接在私信页读的，该会话的未读私信通知都不该继续亮着。
    匹配用聚合键（``dm_dedup_key``）并兼容聚合上线前的存量行（``payload.id`` = 会话 id）。
    """
    from .notifications.sources import dm_dedup_key

    count = 0
    for message in conversation.messages.exclude(read_statuses__user=user):
        _row, created = MessageReadStatus.objects.get_or_create(message=message, user=user)
        count += int(created)
    Notification.objects.filter(
        recipient=user,
        category=Notification.CATEGORY_DM,
        read_at__isnull=True,
    ).filter(
        Q(dedup_key=dm_dedup_key(conversation.pk)) | Q(payload__id=conversation.pk),
    ).update(read_at=timezone.now())
    return count


def retract_dm(message: Message, user) -> Message:
    if message.sender_id != user.pk:
        raise MessagingForbidden("只能撤回自己的消息")
    if message.retracted_at:
        raise MessagingError("消息已撤回")
    if timezone.now() - message.created_at > RETRACT_WINDOW:
        raise MessagingError("已超过撤回时限")
    message.retracted_at = timezone.now()
    message.save(update_fields=["retracted_at", "updated_at"])
    for uid in message.conversation.participants.exclude(pk=user.pk).values_list("id", flat=True):
        push_user(uid, "dm", {
            "conversation_id": message.conversation_id,
            "message_id": message.pk,
            "retracted": True,
        })
    return message


# ---- 内部 ---------------------------------------------------------------

def _host_owner_id(host):
    name = host._meta.model_name
    if name == "news":
        return host.author_id
    if name in ("activity", "task"):
        return host.creator_id
    return None


def _depth(comment: Comment) -> int:
    depth = 1
    current = comment
    seen: set[int] = set()
    while current.parent_id:
        if current.pk in seen:
            break
        seen.add(current.pk)
        current = current.parent
        depth += 1
    return depth


def _mentioned_users(content: str) -> list[User]:
    names = MENTION_RE.findall(content)
    if not names:
        return []
    return list(User.objects.filter(username__in=names, is_active=True))


def _notify_comment(comment: Comment, author, parent: Comment | None) -> None:
    host = host_of(comment.thread)
    payload = {
        "comment_id": comment.pk,
        "thread_id": comment.thread_id,
        "parent_id": parent.pk if parent else None,
        "news_id": comment.thread.news_id,
        "activity_id": comment.thread.activity_id,
        "task_id": comment.thread.task_id,
    }
    seen: set[int] = {author.pk}
    if parent is not None and parent.author_id not in seen:
        notify(
            parent.author, Notification.CATEGORY_COMMENT, "comment_replied",
            actor=author, payload=payload,
        )
        seen.add(parent.author_id)
    for mentioned in _mentioned_users(comment.content):
        if mentioned.pk in seen:
            continue
        if not can_see_host(mentioned, host):
            continue
        notify(
            mentioned, Notification.CATEGORY_COMMENT, "comment_mentioned",
            actor=author, payload=payload,
        )
        seen.add(mentioned.pk)


def _group_send(group: str, event: str, payload: Mapping | None) -> None:
    """Channels 未安装 / 未配置 / 发送失败时静默。type=messaging.event 供 consumer 收。"""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        return
    try:
        layer = get_channel_layer()
    except Exception:
        return
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            group,
            {"type": "messaging.event", "event": event, "payload": dict(payload or {})},
        )
    except Exception:
        logger.debug("channel layer group_send failed group=%s event=%s", group, event, exc_info=True)
