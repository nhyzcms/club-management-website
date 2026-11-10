"""邮箱认证通道（ADR-0006）：verify-email / resend / 登录态。

verify-email：email 通道 pending → approved，identifier 晋升写入 User.email（绑定邮箱生效）。
resend：按 email 通道 identifier 查待验账号重发。登录与认证解耦：未认证可登录（访客），
仅 is_active 拒停用。
"""
import json

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import Verification, is_verified
from accounts.tokens import email_verification_token


def _login(client, **fields):
    return client.post("/auth/login/", data=json.dumps(fields), content_type="application/json")


def make_user(username="someone", password="StrongPass123!"):
    """新建活跃用户（无 Verification 行 ⇒ 未认证 / 访客）。"""
    return User.objects.create_user(username=username, password=password, is_active=True)


def make_pending_email_user(username="someone", email="someone@example.com", password="StrongPass123!"):
    """新建带 pending email 通道的用户（复刻带邮箱注册）：identifier=待认证地址，User.email 仍空。"""
    u = User.objects.create_user(username=username, password=password, is_active=True)
    Verification.objects.create(
        user=u, channel=Verification.CHANNEL_EMAIL,
        status=Verification.STATUS_PENDING, identifier=email,
    )
    return u


def _uid_token(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return uid, email_verification_token.make_token(user)


class VerifyEmailViewTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_pending_email_user()

    def test_verify_success_approves_channel_and_promotes_email(self):
        uid, token = _uid_token(self.user)
        resp = self.client.get(f"/auth/verify-email/?uid={uid}&token={token}")
        self.assertEqual(resp.status_code, 200, resp.content)

        self.user.refresh_from_db()
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.status, Verification.STATUS_APPROVED)
        self.assertEqual(self.user.email, "someone@example.com")  # identifier 晋升写入
        self.assertTrue(is_verified(self.user))  # email 通道 approved ⇒ 已认证

    def test_verify_invalid_token_rejected(self):
        uid, _ = _uid_token(self.user)
        resp = self.client.get(f"/auth/verify-email/?uid={uid}&token=bogus-token")
        self.assertEqual(resp.status_code, 400)
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")  # 未晋升

    def test_verify_tampered_uid_rejected(self):
        _, token = _uid_token(self.user)
        resp = self.client.get(f"/auth/verify-email/?uid=not-a-valid-uid&token={token}")
        self.assertEqual(resp.status_code, 400)

    def test_verify_after_pending_email_change_old_token_invalid(self):
        # 改待认证邮箱（identifier 变）→ 旧令牌失效
        uid, token = _uid_token(self.user)
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        v.identifier = "changed@example.com"
        v.save(update_fields=["identifier"])
        resp = self.client.get(f"/auth/verify-email/?uid={uid}&token={token}")
        self.assertEqual(resp.status_code, 400)

    def test_verify_idempotent_when_already_verified(self):
        # 已 approved：令牌随 status 翻转失效 → 400（不可重放）
        uid, token = _uid_token(self.user)
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        v.status = Verification.STATUS_APPROVED
        v.save(update_fields=["status"])
        resp = self.client.get(f"/auth/verify-email/?uid={uid}&token={token}")
        self.assertEqual(resp.status_code, 400)


class ResendVerificationViewTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_pending_email_user()

    def test_resend_sends_for_pending(self):
        resp = self.client.post(
            "/auth/resend-verification/",
            data=json.dumps({"email": "someone@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("someone@example.com", mail.outbox[0].to)

    def test_resend_no_leak_for_unknown_email(self):
        resp = self.client.post(
            "/auth/resend-verification/",
            data=json.dumps({"email": "nobody@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_no_leak_for_already_verified(self):
        # 已 approved（无 pending 通道）→ 不重发，但提示一致
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        v.status = Verification.STATUS_APPROVED
        v.save(update_fields=["status"])
        resp = self.client.post(
            "/auth/resend-verification/",
            data=json.dumps({"email": "someone@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_throttled(self):
        for _ in range(5):
            self.client.post(
                "/auth/resend-verification/",
                data=json.dumps({"email": "someone@example.com"}),
                content_type="application/json",
            )
        resp = self.client.post(
            "/auth/resend-verification/",
            data=json.dumps({"email": "someone@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 429)

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="secret")
    def test_resend_rejected_without_turnstile_when_enabled(self):
        resp = self.client.post(
            "/auth/resend-verification/",
            data=json.dumps({"email": "someone@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("人机校验", str(resp.json()["error"]))
        self.assertEqual(len(mail.outbox), 0)


class LoginStateTest(TestCase):
    """登录态（ADR-0006 决策 6）：未认证可登录（访客）/ 停用被拒 / 错误密码不泄状态。"""

    def setUp(self):
        cache.clear()

    def test_unverified_can_login(self):
        # 未认证账号（无 Verification 行）也能登录（落地访客，写操作由 IsVerified 另管）
        make_user("uv", password="StrongPass123!")
        resp = _login(self.client, username="uv", password="StrongPass123!")
        self.assertEqual(resp.status_code, 200)

    def test_login_disabled_blocked(self):
        u = make_user("dis", password="StrongPass123!")
        u.is_active = False
        u.save()
        resp = _login(self.client, username="dis", password="StrongPass123!")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "account_disabled")

    def test_wrong_password_does_not_leak_state(self):
        make_user("uv", password="StrongPass123!")
        resp = _login(self.client, username="uv", password="wrong-password")
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("reason", resp.json())
