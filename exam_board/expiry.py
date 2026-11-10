"""题目误刊的到期时刻：跟上海墙钟上的科目场次走，本场结束即失效。"""
from datetime import datetime

from .clock import SHANGHAI, shanghai_now
from .models import ExamSubject


def _at(day, clock):
    return datetime.combine(day, clock, tzinfo=SHANGHAI)


def _active_ends(
    exam_id: int | None = None,
    batch_id: int | None = None,
    now: datetime | None = None,
) -> list[datetime]:
    now = now or shanghai_now()
    today = now.date()
    qs = ExamSubject.objects.filter(exam_date=today)
    if batch_id is not None:
        qs = qs.filter(batch_id=batch_id)
    elif exam_id is not None:
        qs = qs.filter(batch__exam_id=exam_id)
    return [
        _at(today, s.end_time)
        for s in qs.only("start_time", "end_time")
        if _at(today, s.start_time) <= now < _at(today, s.end_time)
    ]


def compute_errata_expiry(
    exam_id: int | None = None,
    batch_id: int | None = None,
    now: datetime | None = None,
) -> datetime:
    """进行中的科目场次取该场结束；当前没有进行中的场次则立刻到期。"""
    now = now or shanghai_now()
    ends = _active_ends(exam_id, batch_id, now)
    return min(ends) if ends else now


def has_active_subject(
    exam_id: int | None = None,
    batch_id: int | None = None,
    now: datetime | None = None,
) -> bool:
    """当前是否有进行中的科目场次（上海墙钟、当天）。"""
    return bool(_active_ends(exam_id, batch_id, now))
