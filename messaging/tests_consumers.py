"""WebsocketCommunicator coverage for /ws/messaging/ (ADR 0015)."""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TransactionTestCase

from config.asgi import application
from messaging.consumers import MessagingConsumer
from messaging.services import thread_for
from news.models import News


def _ws_headers(*extra):
    hosts = [h for h in settings.ALLOWED_HOSTS if h and h != "*"]
    if hosts:
        host = hosts[0].lstrip(".")
    else:
        host = "localhost"
    return [(b"origin", f"http://{host}".encode()), *extra]


class MessagingWebsocketTests(TransactionTestCase):
    def test_anonymous_is_rejected(self):
        async def inner():
            communicator = WebsocketCommunicator(
                application, "/ws/messaging/", headers=_ws_headers(),
            )
            connected, _ = await communicator.connect()
            self.assertFalse(connected)
            await communicator.disconnect()

        async_to_sync(inner)()

    def test_session_user_receives_user_group_event(self):
        user = User.objects.create_user("alice", password="secret123")
        cookie = self._session_cookie(user)

        async def inner():
            communicator = WebsocketCommunicator(
                application,
                "/ws/messaging/",
                headers=_ws_headers(
                    (b"cookie", f"{settings.SESSION_COOKIE_NAME}={cookie}".encode()),
                ),
            )
            connected, code = await communicator.connect()
            self.assertTrue(connected, f"ws rejected code={code}")
            await get_channel_layer().group_send(
                f"user_{user.pk}",
                {
                    "type": "messaging.event",
                    "event": "notification",
                    "payload": {"notification_id": 7},
                },
            )
            self.assertEqual(
                await communicator.receive_json_from(),
                {"event": "notification", "payload": {"notification_id": 7}},
            )
            await communicator.disconnect()

        async_to_sync(inner)()

    def test_subscribe_thread_receives_comment_event(self):
        user = User.objects.create_user("alice", password="secret123")
        thread = self._published_thread(user)

        async def inner():
            communicator = WebsocketCommunicator(
                MessagingConsumer.as_asgi(), "/ws/messaging/",
            )
            communicator.scope["user"] = user
            connected, code = await communicator.connect()
            self.assertTrue(connected, f"ws rejected code={code}")
            await communicator.send_json_to(
                {"action": "subscribe_thread", "thread_id": thread.pk},
            )
            self.assertTrue(await communicator.receive_nothing())
            await get_channel_layer().group_send(
                f"thread_{thread.pk}",
                {
                    "type": "messaging.event",
                    "event": "comment",
                    "payload": {"thread_id": thread.pk, "comment_id": 3},
                },
            )
            self.assertEqual(
                await communicator.receive_json_from(),
                {
                    "event": "comment",
                    "payload": {"thread_id": thread.pk, "comment_id": 3},
                },
            )
            await communicator.send_json_to(
                {"action": "unsubscribe_thread", "thread_id": thread.pk},
            )
            self.assertTrue(await communicator.receive_nothing())
            await get_channel_layer().group_send(
                f"thread_{thread.pk}",
                {
                    "type": "messaging.event",
                    "event": "comment",
                    "payload": {"thread_id": thread.pk, "comment_id": 4},
                },
            )
            self.assertTrue(await communicator.receive_nothing())
            await communicator.disconnect()

        async_to_sync(inner)()

    def _session_cookie(self, user):
        client = Client()
        client.force_login(user)
        return client.cookies[settings.SESSION_COOKIE_NAME].value

    def _published_thread(self, user):
        news = News.objects.create(title="n", author=user, is_published=True)
        return thread_for(news)


class MessagingRevokedSessionTests(TransactionTestCase):
    """M-6 回归：已手动下线 / 安全吊销的会话不能再建 WebSocket。"""

    def test_revoked_session_cannot_connect(self):
        from django.utils import timezone
        from accounts.models import UserSession

        user = User.objects.create_user("ws_revoked", password="secret123")
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get("/auth/me/").status_code, 200)
        UserSession.objects.filter(user=user).update(revoked_at=timezone.now())
        cookie = client.cookies[settings.SESSION_COOKIE_NAME].value

        async def inner():
            communicator = WebsocketCommunicator(
                application,
                "/ws/messaging/",
                headers=_ws_headers(
                    (b"cookie", f"{settings.SESSION_COOKIE_NAME}={cookie}".encode()),
                ),
            )
            connected, _ = await communicator.connect()
            self.assertFalse(connected)
            await communicator.disconnect()

        async_to_sync(inner)()
