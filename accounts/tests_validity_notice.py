"""账号有效期展示口径与一次性提示（ADR-0041）。

覆盖：未认证宽限、已认证 / 管理员 / 超管 / 认证已到期四种状态的到期时间与剩余天数、
``/auth/validity/`` 与 ``/auth/validity/ack/`` 的契约、状态变化后提示重新出现、
以及 ``send_validity_broadcast`` 群发命令（dry-run / 幂等 / 跳过已注销）。
"""
import io
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from messaging.models import Conversation, Message

from accounts.models import Profile, Verification
from accounts.validity_summary import (
    STATUS_ADMIN,
    STATUS_EXPIRED,
    STATUS_PERMANENT,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    account_validity,
    format_dm_message,
)

LOGIN_URL = "/auth/login/"
PASSWORD = "secret123"


def make_user(username, **kwargs):
    user = User.objects.create_user(username=username, password=PASSWORD, **kwargs)
    Profile.objects.create(user=user, real_name=username)
    return user


_UNSET = object()


def approve(user, channel=Verification.CHANNEL_MANUAL, *, days=365, expires_at=_UNSET):
    if expires_at is _UNSET:
        expires_at = timezone.now() + timedelta(days=days)
    return Verification.objects.create(
        user=user,
        channel=channel,
        status=Verification.STATUS_APPROVED,
        verified_at=timezone.now(),
        expires_at=expires_at,
    )


def login(client, username):
    return client.post(
        LOGIN_URL,
        data=json.dumps({"username": username, "password": PASSWORD}),
        content_type="application/json",
    )


def run_broadcast(*args):
    return call_command("send_validity_broadcast", *args, stdout=io.StringIO())


class AccountValiditySnapshotTest(TestCase):
    def test_unverified_uses_registration_deadline(self):
        user = make_user("fresh")
        data = account_validity(user)
        self.assertEqual(data["status"], STATUS_UNVERIFIED)
        self.assertEqual(data["remaining_days"], 60)
        self.assertTrue(data["notice_pending"])
        self.assertTrue(data["key"].startswith("unverified:"))
        self.assertIsNotNone(data["registration_deadline"])
        self.assertEqual(data["policy"]["verification_valid_days"], 365)
        self.assertEqual(data["policy"]["admin_valid_days"], 730)
        self.assertEqual(data["policy"]["registration_verify_days"], 60)

    def test_profile_deadline_override_wins(self):
        user = make_user("late")
        profile = user.profile
        profile.registration_deadline = timezone.now() + timedelta(days=3)
        profile.save(update_fields=["registration_deadline"])
        data = account_validity(user)
        self.assertEqual(data["remaining_days"], 3)
        self.assertEqual(
            data["registration_deadline"],
            profile.registration_deadline.isoformat(),
        )

    def test_verified_uses_last_channel_expiry(self):
        user = make_user("verified")
        approve(user, channel=Verification.CHANNEL_EMAIL, days=30)
        approve(user, channel=Verification.CHANNEL_MANUAL, days=365)
        data = account_validity(user)
        self.assertEqual(data["status"], STATUS_VERIFIED)
        self.assertEqual(data["expires_at"], max(
            row["expires_at"] for row in data["channels"]
        ))
        self.assertEqual(data["remaining_days"], 365)
        self.assertEqual(len(data["channels"]), 2)

    def test_permanent_channel_makes_account_permanent(self):
        user = make_user("forever")
        approve(user, expires_at=None)
        data = account_validity(user)
        self.assertEqual(data["status"], STATUS_VERIFIED)
        self.assertIsNone(data["expires_at"])
        self.assertIsNone(data["remaining_days"])
        self.assertTrue(data["key"].endswith(":forever"))

    def test_staff_uses_appointment_expiry(self):
        user = make_user("admin", is_staff=True)
        data = account_validity(user)
        self.assertEqual(data["status"], STATUS_ADMIN)
        self.assertEqual(data["remaining_days"], 730)

    def test_superuser_is_permanent(self):
        user = User.objects.create_superuser("root", "root@163.com", PASSWORD)
        Profile.objects.create(user=user, real_name="root")
        data = account_validity(user)
        self.assertEqual(data["status"], STATUS_PERMANENT)
        self.assertIsNone(data["expires_at"])
        self.assertIsNone(data["remaining_days"])

    def test_expired_verification_reports_expired(self):
        user = make_user("expired")
        approve(user, expires_at=timezone.now() - timedelta(days=2))
        data = account_validity(user)
        self.assertEqual(data["status"], STATUS_EXPIRED)
        self.assertLessEqual(data["remaining_days"], -1)
        self.assertIn("已到期", data["status_label"])


class ValidityEndpointTest(TestCase):
    def test_anonymous_gets_json_401(self):
        resp = Client().get("/auth/validity/")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"], "未登录。")

    def test_summary_and_ack_roundtrip(self):
        user = make_user("u")
        client = Client()
        login(client, "u")

        first = client.get("/auth/validity/").json()
        self.assertTrue(first["notice_pending"])
        key = first["key"]

        ack = client.post(
            "/auth/validity/ack/",
            data=json.dumps({"key": key}),
            content_type="application/json",
        )
        self.assertEqual(ack.status_code, 200)
        self.assertTrue(ack.json()["acknowledged"])

        second = client.get("/auth/validity/").json()
        self.assertFalse(second["notice_pending"])

        # 旧键不能吞掉新状态：认证通过后键变了，提示重新出现。
        approve(user, days=365)
        third = client.get("/auth/validity/").json()
        self.assertEqual(third["status"], STATUS_VERIFIED)
        self.assertTrue(third["notice_pending"])
        self.assertNotEqual(third["key"], key)

        stale = client.post(
            "/auth/validity/ack/",
            data=json.dumps({"key": key}),
            content_type="application/json",
        )
        self.assertFalse(stale.json()["acknowledged"])
        self.assertTrue(client.get("/auth/validity/").json()["notice_pending"])

    def test_ack_requires_key(self):
        make_user("u")
        client = Client()
        login(client, "u")
        resp = client.post(
            "/auth/validity/ack/",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class BroadcastCommandTest(TestCase):
    def setUp(self):
        self.sender = User.objects.create_superuser("root", "root@163.com", PASSWORD)
        Profile.objects.create(user=self.sender, real_name="root")
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        approve(self.alice, days=365)

        self.gone = make_user("gone")
        self.gone.profile.deleted_at = timezone.now()
        self.gone.profile.save(update_fields=["deleted_at"])

    def _messages(self):
        return Message.objects.filter(sender=self.sender)

    def test_dry_run_does_not_write(self):
        run_broadcast("--dry-run")
        self.assertEqual(self._messages().count(), 0)

    def test_sends_personalized_message_and_is_idempotent(self):
        run_broadcast()
        self.assertEqual(self._messages().count(), 2)  # alice + bob；跳过超管本人与已注销

        to_alice = self._messages().filter(conversation__participants=self.alice).get()
        to_bob = self._messages().filter(conversation__participants=self.bob).get()
        self.assertIn("账号当前状态：已认证用户", to_alice.content)
        self.assertIn("剩余有效期：365 天", to_alice.content)
        self.assertIn("账号当前状态：未认证用户", to_bob.content)
        self.assertIn("认证截止时间", to_bob.content)
        self.assertIn("有效期规则", to_alice.content)
        self.assertEqual(Conversation.objects.filter(participants=self.gone).count(), 0)

        run_broadcast()
        self.assertEqual(self._messages().count(), 2)  # 去重：不重复发

    def test_limit_caps_recipients(self):
        run_broadcast("--limit", "1")
        self.assertEqual(self._messages().count(), 1)

    def test_message_text_mentions_expiry_and_rules(self):
        data = account_validity(self.alice)
        text = format_dm_message(self.alice, data)
        self.assertTrue(text.startswith("【账号有效期说明】"))
        self.assertIn("账号到期时间：", text)
        self.assertIn("剩余有效期：365 天", text)
        self.assertIn("认证有效期 365 天", text)
