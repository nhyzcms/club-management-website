"""活动生命周期（遵循 ADR 0003：状态机与访问控制分离）。

状态流转::

    draft ──publish──> scheduled ──到 start_at──> active ──到 end_at──> ended
                          └──────────（start_at 已过时发布）──────────┘
    ended ──archive──> archived

- ``draft``：只有组织者与管理者可见，可任意编辑；
- ``scheduled`` / ``active``：已上线；``scheduled`` 仍可改时间与内容，``active`` 后锁定；
- ``ended``：到点自动结算。**只读，不可参与**——这是与 activities 的关键差异：
  活动「时间过后自动关闭」是硬契约，所有写入口必须先 ``touch()`` 再判状态；
- ``archived``：组织者/管理员手动归档，从默认列表里收起，数据保留。

无定时任务：与 activities 的惰性方案一致，读取时按时间推进。定时任务的唯一增量
是「到点主动通知」，不在本期范围。
"""
from django.utils import timezone

from .models import Event

DRAFT = Event.STATUS_DRAFT
SCHEDULED = Event.STATUS_SCHEDULED
ACTIVE = Event.STATUS_ACTIVE
ENDED = Event.STATUS_ENDED
ARCHIVED = Event.STATUS_ARCHIVED


def initial_status(start_at, now=None):
    """创建/发布时的目标状态：``start_at`` 在未来 → scheduled，否则 active。"""
    now = now or timezone.now()
    return ACTIVE if start_at <= now else SCHEDULED


def touch():
    """惰性推进：把到点的 scheduled 翻成 active、到点的 active 翻成 ended。

    逐条条件更新（``status=...`` 作为并发门闩），多个读者同时触达只有一个真正生效。
    返回 ``(opened, closed)`` 两组 pk，供调用方决定是否发通知（本期未接）。
    """
    now = timezone.now()
    opened = []
    for pk in Event.objects.filter(
        status=SCHEDULED, start_at__lte=now,
    ).values_list("pk", flat=True):
        if Event.objects.filter(pk=pk, status=SCHEDULED).update(
            status=ACTIVE, updated_at=now,
        ):
            opened.append(pk)

    closed = []
    for pk in Event.objects.filter(
        status=ACTIVE, end_at__isnull=False, end_at__lte=now,
    ).values_list("pk", flat=True):
        if Event.objects.filter(pk=pk, status=ACTIVE).update(
            status=ENDED, updated_at=now,
        ):
            closed.append(pk)

    return opened, closed


# ---- 守卫（纯领域逻辑，不碰 DB）-----------------------------------------

def can_view(event, user):
    """能否看到这条活动（草稿仅组织者与管理者可见）。"""
    if event.status != DRAFT:
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    return event.organizer_id == user.pk or user.has_perm("events.manage_events")


def can_edit(event, user):
    """能否编辑：draft / scheduled 可改；active 起锁定；archived 不可改。

    角色轴由 ``CanModifyEvent`` 权限类在视图层把关，此处只管「此刻能否改」。
    """
    return event.status in (DRAFT, SCHEDULED)


def can_publish(event, user):
    """能否发布：仅 draft。"""
    return event.status == DRAFT


def can_participate(event, user):
    """能否参与（报名 / 提交 / 配对等）：仅 active。

    模块的所有写入口都必须先调 ``touch()`` 再调本函数——否则「到点后还能写」
    会从这里漏出去。
    """
    return event.status == ACTIVE


def can_archive(event, user):
    """能否归档：仅 ended。"""
    return event.status == ENDED


def publish(event):
    """发布：draft → scheduled / active（按 start_at 决定）。调用方须先过 can_publish。"""
    event.status = initial_status(event.start_at)
    event.save(update_fields=["status", "updated_at"])
    return event.status
