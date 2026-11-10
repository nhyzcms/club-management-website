"""站内通知聚合去重 + 私信已读联动（同一未读事项只通知一次）。

产品规则：
- 别人连发多条私信只提示**一次**（每个会话一条未读通知），直到我把这次通知读掉；
- 读私信——不论从通知入口点进去，还是直接开私信页——该会话的未读通知一并变已读；
- 邮件同理：聚合命中的后续消息不再外发邮件（同一个未读事项至多一封）。
"""
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from messaging.models import (
    Conversation,
    Notification,
    NotificationDelivery,
    NotificationSubscription,
)
from messaging.notifications.sources import DM_EVENT, DmSource, dm_dedup_key
from messaging.services import mark_conversation_read, send_dm


class DmNotificationDigestTest(TestCase):
    """私信站内通知按会话聚合。"""

    def setUp(self):
        self.alice = grant_verification(User.objects.create_user("alice", password="x"))
        self.bob = grant_verification(User.objects.create_user("bob", password="x"))
        self.conv = Conversation.objects.create()
        self.conv.participants.set([self.alice, self.bob])

    def _notifications(self, unread_only=False):
        rows = Notification.objects.filter(recipient=self.alice, category="dm")
        return rows.filter(read_at__isnull=True) if unread_only else rows

    def test_dedup_key_agrees_with_source(self):
        self.assertEqual(
            DmSource().dedup_key(DM_EVENT, {"id": self.conv.pk}),
            dm_dedup_key(self.conv.pk),
        )

    def test_repeated_messages_keep_one_unread_notification(self):
        for text in ("第一条", "第二条", "第三条"):
            send_dm(self.conv, self.bob, text)
        self.assertEqual(self._notifications().count(), 1)
        row = self._notifications().get()
        self.assertEqual(row.dedup_key, dm_dedup_key(self.conv.pk))
        self.assertEqual(row.payload["count"], 3)
        self.assertEqual(row.payload["id"], self.conv.pk)
        self.assertEqual(row.payload["url"], f"/messages/{self.conv.pk}")
        self.assertIsNone(row.read_at)

    def test_new_notification_after_read(self):
        send_dm(self.conv, self.bob, "第一条")
        send_dm(self.conv, self.bob, "第二条")
        self.assertEqual(mark_conversation_read(self.alice, self.conv), 2)
        self.assertIsNotNone(self._notifications().get().read_at)
        send_dm(self.conv, self.bob, "第三条")
        self.assertEqual(self._notifications(unread_only=True).count(), 1)
        self.assertEqual(self._notifications().count(), 2)

    def test_mark_read_endpoint_clears_notification(self):
        send_dm(self.conv, self.bob, "在吗")
        client = APIClient()
        client.force_authenticate(self.alice)
        resp = client.post(f"/messaging/conversations/{self.conv.pk}/mark_read/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(self._notifications().get().read_at)
        self.assertEqual(
            client.get("/messaging/notifications/unread_count/").json()["total"], 0,
        )

    def test_notifications_list_shows_merged_count(self):
        send_dm(self.conv, self.bob, "第一条")
        send_dm(self.conv, self.bob, "第二条")
        client = APIClient()
        client.force_authenticate(self.alice)
        results = client.get("/messaging/notifications/").json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["category"], "dm")
        self.assertEqual(results[0]["event"], DM_EVENT)
        self.assertEqual(results[0]["payload"]["count"], 2)

    def test_each_conversation_gets_its_own_unread(self):
        carol = grant_verification(User.objects.create_user("carol", password="x"))
        other = Conversation.objects.create()
        other.participants.set([self.alice, carol])
        send_dm(self.conv, self.bob, "A")
        send_dm(other, carol, "B")
        self.assertEqual(self._notifications(unread_only=True).count(), 2)

    def test_sender_is_not_notified(self):
        send_dm(self.conv, self.bob, "hi")
        self.assertFalse(
            Notification.objects.filter(recipient=self.bob, category="dm").exists()
        )

    def test_legacy_unread_dm_notifications_are_read_too(self):
        """聚合上线前的存量未读行（无聚合键、payload 带会话 id）也被一并标已读。"""
        Notification.objects.create(
            recipient=self.alice, category="dm", event=DM_EVENT,
            payload={"id": self.conv.pk, "url": f"/messages/{self.conv.pk}"},
        )
        send_dm(self.conv, self.bob, "新消息")
        self.assertEqual(self._notifications(unread_only=True).count(), 2)
        mark_conversation_read(self.alice, self.conv)
        self.assertEqual(self._notifications(unread_only=True).count(), 0)

    def test_other_conversation_notification_survives(self):
        carol = grant_verification(User.objects.create_user("carol", password="x"))
        other = Conversation.objects.create()
        other.participants.set([self.alice, carol])
        send_dm(self.conv, self.bob, "A")
        send_dm(other, carol, "B")
        mark_conversation_read(self.alice, self.conv)
        self.assertEqual(self._notifications(unread_only=True).count(), 1)
        self.assertEqual(
            self._notifications(unread_only=True).get().payload["id"], other.pk,
        )


class DmNotificationEmailTest(TestCase):
    """聚合命中的后续消息不再外发邮件（同一个未读事项至多一封）。"""

    def setUp(self):
        self.alice = grant_verification(
            User.objects.create_user("alice", password="x", email="alice@163.com"),
        )
        self.bob = grant_verification(User.objects.create_user("bob", password="x"))
        NotificationSubscription.objects.create(
            user=self.alice, source_key="dm", channel_key="email", enabled=True,
        )
        self.conv = Conversation.objects.create()
        self.conv.participants.set([self.alice, self.bob])

    def test_only_first_message_creates_email_delivery(self):
        with self.captureOnCommitCallbacks(execute=True):
            send_dm(self.conv, self.bob, "第一条")
        send_dm(self.conv, self.bob, "第二条")
        send_dm(self.conv, self.bob, "第三条")
        self.assertEqual(
            NotificationDelivery.objects.filter(channel_key="email").count(), 1,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("新私信", mail.outbox[0].subject)

    def test_email_sent_again_after_read(self):
        with self.captureOnCommitCallbacks(execute=True):
            send_dm(self.conv, self.bob, "第一条")
        mark_conversation_read(self.alice, self.conv)
        with self.captureOnCommitCallbacks(execute=True):
            send_dm(self.conv, self.bob, "第二条")
        self.assertEqual(
            NotificationDelivery.objects.filter(channel_key="email").count(), 2,
        )
        self.assertEqual(len(mail.outbox), 2)
