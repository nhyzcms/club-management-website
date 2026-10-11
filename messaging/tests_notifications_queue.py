"""通知外发投递队列测试（ADR-0024）。

覆盖：入队与排空、失败退避、超限终态、认领互斥、扫描兜底、队列满降级、
共享 SMTP 连接复用、同步回退路径回归、消费线程生命周期。

用例内直接驱动 ``_process_one`` / ``drain_now``（不依赖真实线程调度），
仅在生命周期用例中真实启动 / 停止线程；数据库可见性不受跨线程问题影响。
"""
from __future__ import annotations

import queue as std_queue
import time
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.test_helpers import grant_verification
from messaging.models import Notification, NotificationDelivery, NotificationSubscription
from messaging.notifications import queue as delivery_queue
from messaging.notifications.registry import get_channel
from messaging.services import notify


def _make_user(username="quinn", email="quinn@163.com", verified=True):
    user = User.objects.create_user(username, password="x", email=email)
    return grant_verification(user) if verified else user


def _make_delivery(user, *, channel_key="email", **kwargs):
    """直接造一条投递行（绕过订阅链路，精确控制初始状态）。"""
    notification = Notification.objects.create(
        recipient=user, category="comment", event="comment_replied",
        payload={"url": "/thread/1", "title": "测试帖"},
    )
    return NotificationDelivery.objects.create(
        notification=notification, channel_key=channel_key, **kwargs,
    )


class NotificationQueueTest(TestCase):
    """队列核心路径。"""

    def setUp(self):
        self.user = _make_user()
        NotificationSubscription.objects.create(
            user=self.user, source_key="comment", channel_key="email", enabled=True,
        )

    def tearDown(self):
        delivery_queue.stop_worker()
        delivery_queue._q = None
        delivery_queue._last_sweep = 0.0

    def _notify_with_capture(self, *, patch_worker=True):
        """触发一次通知并把 on_commit 回调执行掉；默认不启动真实消费线程。"""
        ctx = mock.patch.object(delivery_queue, "_ensure_worker") if patch_worker \
            else mock.patch.object(delivery_queue, "_ensure_worker", wraps=delivery_queue._ensure_worker)
        with ctx:
            with self.captureOnCommitCallbacks(execute=True):
                notify(self.user, "comment", "comment_replied", payload={"url": "/x"})

    # -- 回归：默认（测试期）走同步投递，行为与历史一致 ----------------------

    def test_sync_mode_is_test_default(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify(self.user, "comment", "comment_replied", payload={"url": "/x"})
        delivery = NotificationDelivery.objects.get(channel_key="email")
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_SENT)
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(len(mail.outbox), 1)

    # -- 异步主路径 -----------------------------------------------------------

    @override_settings(NOTIFICATIONS_DELIVERY_ASYNC=True)
    def test_async_enqueue_then_drain(self):
        self._notify_with_capture()
        delivery = NotificationDelivery.objects.get(channel_key="email")
        # 已入队、尚未投递
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_PENDING)
        self.assertEqual(len(mail.outbox), 0)

        processed = delivery_queue.drain_now()
        self.assertEqual(processed, 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_SENT)
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(NOTIFICATIONS_DELIVERY_ASYNC=True)
    def test_async_failure_schedules_backoff(self):
        self._notify_with_capture()
        delivery = NotificationDelivery.objects.get(channel_key="email")
        with mock.patch.object(
            get_channel("email"), "deliver", side_effect=RuntimeError("SMTP 模拟故障"),
        ):
            processed = delivery_queue.drain_now()
        self.assertEqual(processed, 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_PENDING)
        self.assertEqual(delivery.attempts, 1)
        self.assertIn("SMTP 模拟故障", delivery.last_error)
        # 1 分钟后重试（退避第 1 档）
        self.assertGreater(delivery.next_retry_at, timezone.now() + timedelta(seconds=30))
        self.assertLess(delivery.next_retry_at, timezone.now() + timedelta(minutes=2))
        self.assertEqual(len(mail.outbox), 0)

    def test_retry_exhaustion_marks_failed(self):
        delivery = _make_delivery(self.user, attempts=5, next_retry_at=timezone.now())
        with mock.patch.object(
            get_channel("email"), "deliver", side_effect=RuntimeError("重试仍失败"),
        ):
            outcome = delivery_queue._process_one(delivery.pk)
        self.assertEqual(outcome, "failed")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_FAILED)
        self.assertEqual(delivery.attempts, 6)

    def test_locked_delivery_is_skipped(self):
        # next_retry_at 在未来 = 已（被他人）认领 / 尚未到期 → 跳过
        delivery = _make_delivery(self.user, next_retry_at=timezone.now() + timedelta(minutes=3))
        self.assertEqual(delivery_queue._process_one(delivery.pk), "skip")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_PENDING)
        self.assertEqual(len(mail.outbox), 0)

    def test_sweep_recovers_pending(self):
        # 模拟进程重启残漏：pending 行留在库中、无人在内存队列里
        delivery = _make_delivery(self.user)
        processed = delivery_queue.sweep()
        self.assertEqual(processed, 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_SENT)
        self.assertEqual(len(mail.outbox), 1)

    def test_sweep_skips_not_due_rows(self):
        _make_delivery(self.user, next_retry_at=timezone.now() + timedelta(minutes=10))
        self.assertEqual(delivery_queue.sweep(), 0)

    def test_unavailable_recipient_marks_failed(self):
        unverified = _make_user("unverified", email="u@163.com", verified=False)
        delivery = _make_delivery(unverified)
        outcome = delivery_queue._process_one(delivery.pk)
        self.assertEqual(outcome, "failed")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_FAILED)
        self.assertIn("不可用", delivery.last_error)

    # -- 降级与连接复用 -------------------------------------------------------

    @override_settings(NOTIFICATIONS_DELIVERY_ASYNC=True)
    def test_queue_full_defers_to_sweep(self):
        full_q = std_queue.Queue(maxsize=1)
        full_q.put_nowait(99999)  # 占满（假 id，处理时自然 skip）
        with mock.patch.object(delivery_queue, "_ensure_worker"), \
             mock.patch.object(delivery_queue, "_q", full_q):
            with self.assertLogs("messaging.notifications.queue", level="WARNING"):
                with self.captureOnCommitCallbacks(execute=True):
                    notify(self.user, "comment", "comment_replied", payload={"url": "/x"})
        delivery = NotificationDelivery.objects.get(channel_key="email")
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_PENDING)
        # 兜底扫描补齐（队列满不丢）
        self.assertEqual(delivery_queue.sweep(), 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_SENT)

    def test_shared_connection_reused_across_batch(self):
        conn = mock.MagicMock()
        delivered_connections = []

        def fake_deliver(delivery, *, connection=None):
            delivered_connections.append(connection)

        with mock.patch.object(
            delivery_queue.django_mail, "get_connection", return_value=conn,
        ), mock.patch.object(get_channel("email"), "deliver", side_effect=fake_deliver):
            d1 = _make_delivery(self.user)
            d2 = _make_delivery(self.user)
            self.assertEqual(delivery_queue._process_one(d1.pk), "sent")
            self.assertEqual(delivery_queue._process_one(d2.pk), "sent")

        self.assertEqual(delivered_connections, [conn, conn])  # 同一连接复用
        self.assertGreaterEqual(conn.open.call_count, 1)

    # -- 消费线程生命周期 -----------------------------------------------------

    def test_worker_lifecycle(self):
        self.assertIsNone(delivery_queue._worker)
        delivery_queue._ensure_worker()
        self.assertIsNotNone(delivery_queue._worker)
        self.assertTrue(delivery_queue._worker.is_alive())
        self.assertTrue(delivery_queue._worker.daemon)
        self.assertEqual(delivery_queue._worker.name, "notif-delivery")
        delivery_queue.stop_worker()
        self.assertIsNone(delivery_queue._worker)
        time.sleep(0.05)
