"""已认证成员待办收件箱（#82）：``GET /auth/inbox/``。

混合时间线：活动债、任务债。48h 内截止的活动债置顶（end_at 升序），
其余按 updated_at 降序。不分页（ADR-0008 数字分页会把债拆进后页）。
私信未读不进待办（私信有自己的未读计数）。
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from activities.debt import activity_debt_reason, activity_debts_for
from activities.serializers import ActivityListSerializer
from tasks.debt import task_debt_reason, task_debts_for
from tasks.serializers import TaskListSerializer

from .permissions import IsVerified

PIN_WINDOW = timedelta(hours=48)


def _is_pinned(end_at, now):
    return end_at is not None and now < end_at <= now + PIN_WINDOW


def _activity_item(activity, request, now):
    has_ballot = bool(getattr(activity, "_has_ballot", False))
    has_submission = bool(getattr(activity, "_has_submission", False))
    return {
        "kind": "activity",
        "reason": activity_debt_reason(
            activity, has_ballot=has_ballot, has_submission=has_submission,
        ),
        "pinned": _is_pinned(activity.end_at, now),
        "updated_at": activity.updated_at,
        "end_at": activity.end_at,
        "activity": ActivityListSerializer(activity, context={"request": request}).data,
        "task": None,
        "conversation": None,
    }


def _task_item(task, request, now, user):
    is_collaborator = any(u.pk == user.pk for u in task.collaborators.all())
    return {
        "kind": "task",
        "reason": task_debt_reason(task, user, is_collaborator=is_collaborator),
        "pinned": False,
        "updated_at": task.updated_at,
        "end_at": None,
        "activity": None,
        "task": TaskListSerializer(task, context={"request": request}).data,
        "conversation": None,
    }


def build_inbox(request):
    user = request.user
    now = timezone.now()
    items = []
    for activity in activity_debts_for(user):
        items.append(_activity_item(activity, request, now))
    for task in task_debts_for(user):
        items.append(_task_item(task, request, now, user))
    pinned = [i for i in items if i["pinned"]]
    rest = [i for i in items if not i["pinned"]]
    pinned.sort(key=lambda i: i["end_at"])
    rest.sort(key=lambda i: i["updated_at"], reverse=True)
    return pinned + rest


class InboxView(APIView):
    """``GET /auth/inbox/``：当前用户全量债集，DRF 列表信封、永不翻页。"""

    permission_classes = [IsVerified]

    def get(self, request):
        results = build_inbox(request)
        return Response({
            "count": len(results),
            "next": None,
            "previous": None,
            "results": results,
        })
