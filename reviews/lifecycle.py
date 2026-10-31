"""审核状态机（ADR-0003：状态转移不是访问控制，与 permission_classes 分离）。"""
from django.utils import timezone

from common.policy import get_policy
from common.targets import content_host, kind_of
from messaging.services import notify, notify_all, notify_perm

from .models import Review

APPROVE = "approve"
REJECT = "reject"
REMOVE = "remove"

_ALLOWED = {
    APPROVE: (Review.STATUS_PENDING, Review.STATUS_REMOVED),
    REJECT: (Review.STATUS_PENDING,),
    REMOVE: (Review.STATUS_APPROVED,),
}

_NOTIFY_EVENT = {
    APPROVE: "approved",
    REJECT: "rejected",
    REMOVE: "removed",
}

_HOST_URL = {
    "news": "/news/{id}",
    "activity": "/activity/{id}",
    "tutorial": "/tutorials/{id}",
}


class TransitionDenied(Exception):
    """当前状态不允许该审核动作。"""


def open_review(*, news=None, activity=None, tutorial=None, actor, force_publish=None):
    """为新对象打开一条审核。免审发布者或内容审核关闭时直接通过，否则待审。

    是否免审由 ``reviews.force_publish`` 判定（调用方不必再查权限）。
    站点策略 ``content_review_enabled`` 关闭时等同免审；已有待审条目不受影响。
    """
    if force_publish is None:
        force_publish = bool(actor and actor.has_perm("reviews.force_publish"))
    kwargs = {"news": news, "activity": activity, "tutorial": tutorial}
    if force_publish or not get_policy().content_review_enabled:
        review = Review.objects.create(
            **kwargs,
            status=Review.STATUS_APPROVED,
            moderated_by=actor,
            moderated_at=timezone.now(),
        )
        _notify_activity_published_if(review, actor)
        return review
    review = Review.objects.create(**kwargs, status=Review.STATUS_PENDING)
    _notify_reviewers(review, actor)
    return review


def reopen_on_edit(*, news=None, activity=None, tutorial=None, actor):
    """已过审（或已驳回）的宿主被实质修改 → 退回待审，重新走一遍审核。

    审核只对「提交时的版本」有效：否则先提交良性版本过审、通过后再把正文换成
    同源 iframe / 钓鱼内容，对象仍显示 approved，审核形同虚设（审计 H-5）。

    免审发布者（``reviews.force_publish``）与站点关闭审核时不复位——与
    ``open_review`` 的免审口径保持一致。仅 approved / rejected 复位；
    pending 保持 pending，removed 不因编辑自动恢复（需重新走人工流程）。
    """
    if actor is not None and actor.has_perm("reviews.force_publish"):
        return None
    if not get_policy().content_review_enabled:
        return None
    lookup = {
        key: value
        for key, value in {"news": news, "activity": activity, "tutorial": tutorial}.items()
        if value is not None
    }
    if not lookup:
        return None
    review = Review.objects.filter(**lookup).first()
    if review is None or review.status not in (Review.STATUS_APPROVED, Review.STATUS_REJECTED):
        return review

    review.status = Review.STATUS_PENDING
    review.moderation_note = ""
    review.moderated_by = None
    review.moderated_at = None
    review.save(
        update_fields=[
            "status", "moderation_note", "moderated_by", "moderated_at", "updated_at",
        ]
    )
    _notify_reviewers(review, actor)
    return review


def apply(action, review, user, *, comment=""):
    """执行通过 / 驳回 / 下架。非法转移抛 TransitionDenied。"""
    allowed = _ALLOWED.get(action)
    if allowed is None or review.status not in allowed:
        raise TransitionDenied("当前状态不可执行该审核动作")
    if action == REJECT and not (comment or "").strip():
        raise TransitionDenied("请填写驳回评语")

    review.moderated_by = user
    review.moderated_at = timezone.now()
    if action == APPROVE:
        review.status = Review.STATUS_APPROVED
        review.moderation_note = (comment or "").strip()
    elif action == REJECT:
        review.status = Review.STATUS_REJECTED
        review.moderation_note = comment.strip()
    else:
        review.status = Review.STATUS_REMOVED
        review.moderation_note = (comment or "").strip()
    review.save(update_fields=["status", "moderation_note", "moderated_by", "moderated_at", "updated_at"])
    _notify_owner(review, action, user)
    if action == APPROVE:
        _notify_activity_published_if(review, user)
    return review


def _notify_owner(review, action, actor):
    """审核结果通知宿主主人（新闻作者 / 活动发起人 / 教程上传者）。"""
    host, owner, kind = _host_owner(review)
    if host is None or owner is None:
        return
    event = _NOTIFY_EVENT.get(action)
    if not event:
        return
    notify(
        owner,
        "review",
        event,
        actor=actor,
        payload={
            "type": kind,
            "id": host.pk,
            "url": _HOST_URL[kind].format(id=host.pk),
        },
    )


def _host_title(kind, host):
    return getattr(host, "title", "") or ""


def _notify_reviewers(review, actor):
    """待审内容 → 通知持 ``reviews.moderate`` 的审核者（权限驱动投递）。"""
    host, _, kind = _host_owner(review)
    if host is None:
        return
    notify_perm(
        "review",
        "content_submitted",
        "reviews.moderate",
        actor=actor,
        payload={
            "type": kind,
            "id": host.pk,
            "title": _host_title(kind, host),
            "url": _HOST_URL[kind].format(id=host.pk),
        },
    )


def _notify_activity_published_if(review, actor):
    """活动上线（免审直过或审核通过）后向全体订阅者广播。"""
    if review.status != Review.STATUS_APPROVED:
        return
    host, _, kind = _host_owner(review)
    if host is None or kind != "activity":
        return
    notify_all(
        "activity",
        "published",
        actor=actor,
        payload={
            "type": "activity",
            "id": host.pk,
            "title": _host_title(kind, host),
            "url": _HOST_URL[kind].format(id=host.pk),
        },
    )


_OWNER_ATTR = {"news": "author", "activity": "creator", "tutorial": "uploader"}


def _host_owner(review):
    """审核行 → (宿主, 宿主主人, kind)。

    切读期走 target 并回落旧列；宿主主人字段名三者不同，用 kind 映射。
    """
    host = content_host(review)
    if host is None:
        return None, None, None
    kind = kind_of(host)
    owner = getattr(host, _OWNER_ATTR.get(kind, ""), None)
    return host, owner, kind
