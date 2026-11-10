"""考试看板用上海墙钟。全局 TIME_ZONE 仍是 UTC，科目日期/时刻按 Asia/Shanghai 解读。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

SHANGHAI = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    return timezone.now().astimezone(SHANGHAI)


def clock_payload() -> dict:
    now = timezone.now()
    local = now.astimezone(SHANGHAI)
    return {
        "timestamp": int(now.timestamp() * 1000),
        "timezone": "Asia/Shanghai",
        "iso": local.isoformat(),
    }
