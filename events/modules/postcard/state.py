"""明信片互寄 · 活动 5 阶段状态机（时间惰性推导，方案 docs/plans/postcard-exchange.md §2）。

阶段不是存储字段而是**推导值**：管理员改节点时间即改阶段，无需手动切状态、
无需定时任务（与 events.lifecycle 的惰性方案同思路）。调用方先 ``touch()``
推进 Event 壳层状态，再取 ``phase_of()``。

::

    未开始 ──start_at──> 登记中 ──ship_at──> 已寄出 ──distribute_at──> 下发中 ──end_at──> 已结束

- ``ship_at`` / ``distribute_at`` 可空 = 跳过该阶段；
- Event 为 draft（未发布）→ 未开始；archived → 已结束；
- **仅「登记中」开放登记**（``can_register``），其余阶段用户侧只读公告与进度。
"""
from __future__ import annotations

from django.utils import timezone

from events import lifecycle
from events.models import Event

from .models import PostcardConfig

PHASE_NOT_STARTED = "not_started"
PHASE_REGISTERING = "registering"
PHASE_SHIPPED = "shipped"
PHASE_DISTRIBUTING = "distributing"
PHASE_ENDED = "ended"

PHASE_CHOICES = [
    (PHASE_NOT_STARTED, "未开始"),
    (PHASE_REGISTERING, "登记中"),
    (PHASE_SHIPPED, "已寄出"),
    (PHASE_DISTRIBUTING, "下发中"),
    (PHASE_ENDED, "已结束"),
]
PHASE_LABELS = dict(PHASE_CHOICES)


def current_event(*, include_draft: bool = False):
    """取当前明信片活动：最新一个 module_key=postcard 的活动（无则 None）。

    公开端点不含草稿（未发布 = 用户视角「未开始」）；管理端 ``include_draft=True``
    把草稿也纳入——否则配置页看不到已建未发的活动，PUT 会重复建壳。
    归档的也算「已结束」语义，但优先取未归档的；同届多场时取 start_at 最新。
    """
    lifecycle.touch()
    qs = Event.objects.filter(module_key="postcard")
    if not include_draft:
        qs = qs.exclude(status=Event.STATUS_DRAFT)
    active = qs.exclude(status=Event.STATUS_ARCHIVED).order_by("-start_at", "-id").first()
    if active is not None:
        return active
    return qs.order_by("-start_at", "-id").first()


def phase_of(event: Event | None, config: PostcardConfig | None, now=None) -> str:
    """推导此刻阶段。event/config 为 None（从未配置过）→ 未开始。"""
    if event is None or config is None:
        return PHASE_NOT_STARTED
    now = now or timezone.now()
    if event.status == Event.STATUS_DRAFT:
        return PHASE_NOT_STARTED
    if event.status in (Event.STATUS_ENDED, Event.STATUS_ARCHIVED):
        return PHASE_ENDED
    # scheduled（未到 start_at）→ 未开始；active 后按节点时间细分。
    if event.status == Event.STATUS_SCHEDULED or now < event.start_at:
        return PHASE_NOT_STARTED
    if config.distribute_at and now >= config.distribute_at:
        if event.end_at and now >= event.end_at:
            return PHASE_ENDED
        return PHASE_DISTRIBUTING
    if config.ship_at and now >= config.ship_at:
        return PHASE_SHIPPED
    if event.end_at and now >= event.end_at:
        return PHASE_ENDED
    return PHASE_REGISTERING


def can_register(phase: str) -> bool:
    """仅「登记中」开放登记（需求解释 #1，用户已认可）。"""
    return phase == PHASE_REGISTERING


def progress_nodes(event: Event | None, config: PostcardConfig | None, now=None):
    """进度条节点：[{key,label,time,reached}]，时间未配置的节点 time=None 照样展示。"""
    if event is None or config is None:
        return []
    now = now or timezone.now()
    nodes = [
        ("start", "登记开始", event.start_at),
        ("ship", "已寄出", config.ship_at),
        ("distribute", "下发中", config.distribute_at),
        ("end", "活动结束", event.end_at),
    ]
    return [
        {
            "key": key,
            "label": label,
            "time": time.isoformat() if time else None,
            "reached": bool(time and now >= time),
        }
        for key, label, time in nodes
    ]
