"""意见反馈状态机（ADR-0003：状态转移不是访问控制，与 permission_classes 分离）。"""
from django.utils import timezone

from messaging.services import notify, notify_perm

from .models import Feedback


class FeedbackDenied(Exception):
    """当前状态不允许该反馈动作。"""


def submit(*, title, description="", category, contact="", creator=None):
    """创建一条待处理反馈。匿名 ``creator=None``；署名才记创建人。

    新反馈按权限通知处理者（``reviews.read_feedback``）。
    """
    feedback = Feedback.objects.create(
        title=title,
        description=description or "",
        category=category,
        contact=contact or "",
        creator=creator,
        status=Feedback.STATUS_PENDING,
    )
    notify_perm(
        "review",
        "feedback_submitted",
        "reviews.read_feedback",
        payload={
            "type": "feedback",
            "id": feedback.pk,
            "title": feedback.title,
            "url": f"/feedback/{feedback.pk}",
        },
    )
    return feedback


def close(feedback, actor, *, note=""):
    """了结一条待处理反馈。非法转移抛 FeedbackDenied。"""
    if feedback.status != Feedback.STATUS_PENDING:
        raise FeedbackDenied("当前状态不可了结")
    note = (note or "").strip()
    feedback.status = Feedback.STATUS_CLOSED
    feedback.moderated_by = actor
    feedback.moderated_at = timezone.now()
    feedback.moderation_note = note
    feedback.save(update_fields=["status", "moderated_by", "moderated_at", "moderation_note", "updated_at"])
    if feedback.creator_id is not None:
        payload = {
            "type": "feedback",
            "id": feedback.pk,
            "url": f"/feedback/{feedback.pk}",
        }
        if note:
            payload["reason"] = note
        notify(
            feedback.creator,
            "review",
            "closed",
            actor=actor,
            payload=payload,
        )
    return feedback
