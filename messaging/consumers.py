"""WebSocket 只推送：进 ``user_{id}``，可选订 ``thread_{id}``。

组播体由 ``messaging.services._group_send`` 约定：
``{"type": "messaging.event", "event": ..., "payload": {...}}``。
本 consumer 的 handler 名是 ``messaging_event``；不另起协议。
"""
from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import CommentThread
from .services import MessagingError, can_see_thread


class MessagingConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close()
            return
        self.user_id = user.pk
        self.thread_ids: set[int] = set()
        await self.channel_layer.group_add(f"user_{self.user_id}", self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if getattr(self, "user_id", None) is None or self.channel_layer is None:
            return
        await self.channel_layer.group_discard(f"user_{self.user_id}", self.channel_name)
        for thread_id in list(getattr(self, "thread_ids", ())):
            await self.channel_layer.group_discard(
                f"thread_{thread_id}", self.channel_name,
            )
        self.thread_ids.clear()

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            return
        action = content.get("action")
        if action == "subscribe_thread":
            await self._subscribe_thread(content)
        elif action == "unsubscribe_thread":
            await self._unsubscribe_thread(content)

    async def messaging_event(self, event):
        await self.send_json({
            "event": event.get("event"),
            "payload": event.get("payload") or {},
        })

    async def _subscribe_thread(self, content):
        thread_id = _thread_id(content)
        if thread_id is None:
            return
        user = self.scope.get("user")
        if not await _can_see_thread(user, thread_id):
            return
        await self.channel_layer.group_add(f"thread_{thread_id}", self.channel_name)
        self.thread_ids.add(thread_id)

    async def _unsubscribe_thread(self, content):
        thread_id = _thread_id(content)
        if thread_id is None:
            return
        await self.channel_layer.group_discard(f"thread_{thread_id}", self.channel_name)
        self.thread_ids.discard(thread_id)


def _thread_id(content) -> int | None:
    raw = content.get("thread_id")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


@database_sync_to_async
def _can_see_thread(user, thread_id: int) -> bool:
    try:
        thread = CommentThread.objects.select_related().get(pk=thread_id)
    except CommentThread.DoesNotExist:
        return False
    try:
        return can_see_thread(user, thread)
    except MessagingError:
        return False
