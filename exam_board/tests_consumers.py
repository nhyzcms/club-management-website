"""公开 /ws/exam-board/ 组播（ADR 0018）。"""
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from config.asgi import application
from exam_board.push import GROUP


def _ws_headers(*extra):
    hosts = [h for h in settings.ALLOWED_HOSTS if h and h != "*"]
    host = hosts[0].lstrip(".") if hosts else "localhost"
    return [(b"origin", f"http://{host}".encode()), *extra]


class ExamBoardWebsocketTests(TransactionTestCase):
    def test_anonymous_is_accepted(self):
        async def inner():
            communicator = WebsocketCommunicator(
                application, "/ws/exam-board/", headers=_ws_headers(),
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.disconnect()

        async_to_sync(inner)()

    def test_broadcast_reaches_all_clients(self):
        async def inner():
            a = WebsocketCommunicator(application, "/ws/exam-board/", headers=_ws_headers())
            b = WebsocketCommunicator(application, "/ws/exam-board/", headers=_ws_headers())
            self.assertTrue((await a.connect())[0])
            self.assertTrue((await b.connect())[0])
            await get_channel_layer().group_send(
                GROUP,
                {"type": "exam.board.event", "event": "errata", "payload": {"text": "更正"}},
            )
            self.assertEqual(
                await a.receive_json_from(),
                {"event": "errata", "payload": {"text": "更正"}},
            )
            self.assertEqual(
                await b.receive_json_from(),
                {"event": "errata", "payload": {"text": "更正"}},
            )
            await a.disconnect()
            await b.disconnect()

        async_to_sync(inner)()

    def test_http_publish_pushes_errata(self):
        user = User.objects.create_user("info", password="x")
        user.user_permissions.add(Permission.objects.get(codename="manage_exams"))
        client = APIClient()
        client.force_authenticate(user)
        from exam_board.models import Exam, ExamBatch

        exam = Exam.objects.create(title="期末")
        ExamBatch.objects.create(exam=exam, name="高一", sort_order=0)

        async def inner():
            communicator = WebsocketCommunicator(
                application, "/ws/exam-board/", headers=_ws_headers(),
            )
            self.assertTrue((await communicator.connect())[0])
            resp = await sync_to_async(client.post)(
                "/exam_board/errata/",
                {"text": "第1题印刷错误", "exam": exam.id},
                format="multipart",
            )
            self.assertEqual(resp.status_code, 201)
            msg = await communicator.receive_json_from()
            self.assertEqual(msg["event"], "errata")
            self.assertEqual(msg["payload"]["text"], "第1题印刷错误")
            await communicator.disconnect()

        async_to_sync(inner)()

    def test_broadcast_helper_sends_exam_event(self):
        async def inner():
            communicator = WebsocketCommunicator(
                application, "/ws/exam-board/", headers=_ws_headers(),
            )
            self.assertTrue((await communicator.connect())[0])
            await get_channel_layer().group_send(
                GROUP,
                {"type": "exam.board.event", "event": "exam", "payload": {"exam_id": 9}},
            )
            self.assertEqual(
                await communicator.receive_json_from(),
                {"event": "exam", "payload": {"exam_id": 9}},
            )
            await communicator.disconnect()

        async_to_sync(inner)()
