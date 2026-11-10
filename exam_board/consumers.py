"""公开考试看板推送：进组 ``exam_board``，只收不发。

访客（教室大屏）可连。组播体：
``{"type": "exam.board.event", "event": ..., "payload": {...}}``。
HTTP 仍是事实源；本 socket 只提示刷新。
"""
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .push import GROUP


class ExamBoardConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if self.channel_layer is None:
            return
        await self.channel_layer.group_discard(GROUP, self.channel_name)

    async def receive_json(self, content, **kwargs):
        return

    async def exam_board_event(self, event):
        await self.send_json({
            "event": event.get("event"),
            "payload": event.get("payload") or {},
        })
