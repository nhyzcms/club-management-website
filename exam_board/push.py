"""考试看板组播：组 ``exam_board``，type=exam.board.event。失败静默（与 messaging 同形）。"""
from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

GROUP = "exam_board"


def broadcast(event: str, payload: Mapping | None = None) -> None:
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
            GROUP,
            {"type": "exam.board.event", "event": event, "payload": dict(payload or {})},
        )
    except Exception:
        logger.debug("exam board group_send failed event=%s", event, exc_info=True)
