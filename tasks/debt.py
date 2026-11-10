"""任务债谓词（#82）：收件箱任务行。不复用 ``my_tasks`` / ``available_actions``。"""
from django.db.models import Q

from .models import Task

REASON_COMPLETE = "complete"
REASON_APPROVE_COMPLETION = "approve_completion"
REASON_APPROVE_CLAIM = "approve_claim"


def task_debt_reason(task, user, *, is_collaborator=None):
    """返回 ``complete`` / ``approve_completion`` / ``approve_claim`` / None。"""
    if is_collaborator is None:
        is_collaborator = task.collaborators.filter(pk=user.pk).exists()
    is_assignee = task.assignee_id == user.pk
    if task.status == "in_progress" and (is_assignee or is_collaborator):
        return REASON_COMPLETE
    if task.status == "reviewing" and task.creator_id == user.pk:
        return REASON_APPROVE_COMPLETION
    if task.status == "review" and task.creator_id == user.pk:
        return REASON_APPROVE_CLAIM
    return None


def task_debts_for(user):
    """当前用户作为负责人/协作者/创建人仍欠行动的任务。"""
    return (
        Task.objects.filter(
            Q(status="in_progress", assignee=user)
            | Q(status="in_progress", collaborators=user)
            | Q(status="reviewing", creator=user)
            | Q(status="review", creator=user)
        )
        .select_related("creator", "creator__profile", "assignee", "assignee__profile")
        .prefetch_related("tags", "collaborators")
        .distinct()
    )
