"""邮箱验证通道端到端（#37）：面板 绑定 / 重发 / 换邮 + 邮箱登录只认 User.email + 重置需绑定邮箱。

核心生命周期（注册带邮箱 / verify-email / 晋升 User.email）见 tests_verify；本文件覆盖面板
驱动的绑定动作及其安全断言。

用例邮箱统一用白名单内域名（@163.com），否则会被后缀白名单拦下（见 tests_email_domain / ADR-0023）。
"""
import json

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import Verification
from accounts.tokens import email_verification_token

BIND = "/auth/verification/email/bind/"


def _bind(client, email):
    return client.post(BIND, data=json.dumps({"email": email}), content_type="application/json")


def _login(client, **fields):
    return client.post("/auth/login/", data=json.dumps(fields), content_type="application/json")


def make_approved_email_user(username="u", email="u@163.com", password="StrongPass123!"):
    """已绑定（验证通过）邮箱的用户：email 通道 approved + User.email = identifier。"""
    u = User.objects.create_user(username=username, password=password, is_active=True)
    u.email = email
    u.save()
    Verification.objects.create(
        user=u, channel=Verification.CHANNEL_EMAIL,
        status=Verification.STATUS_APPROVED, identifier=email,
    )
    return u


class EmailBindTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="u", password="p", is_active=True)

    def _client(self):
        c = Client()
        c.force_login(self.user)
        return c

    def test_bind_creates_pending_channel_user_email_untouched(self):
        resp = _bind(self._client(), "new@163.com")
        self.assertEqual(resp.status_code, 200, resp.content)

        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        self.assertEqual(v.identifier, "new@163.com")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")  # User.email 未变（待验邮箱不住此）
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("new@163.com", mail.outbox[0].to)

    def test_bind_requires_login(self):
        self.assertEqual(_bind(Client(), "new@163.com").status_code, 302)

    def test_bind_rejects_invalid_email(self):
        self.assertEqual(_bind(self._client(), "not-an-email").status_code, 400)

    def test_bind_rejects_taken_verified_email(self):
        make_approved_email_user("other", "taken@163.com")
        resp = _bind(self._client(), "taken@163.com")
        self.assertEqual(resp.status_code, 400)

    def test_bind_rejects_taken_pending_identifier(self):
        # 他账号正在验 pending@163.com → 本账号不可绑同邮箱
        other = User.objects.create_user(username="other", password="p")
        Verification.objects.create(
            user=other, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING, identifier="pending@163.com",
        )
        resp = _bind(self._client(), "pending@163.com")
        self.assertEqual(resp.status_code, 400)

    def test_bind_own_pending_email_resends(self):
        # 自家 pending 同邮箱再绑 = 重发（不判自己占用）
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING, identifier="mine@163.com",
        )
        resp = _bind(self._client(), "mine@163.com")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_change_email_keeps_old_until_new_verified(self):
        # 已绑定 old → 换绑 new：通道回 pending(identifier=new)，User.email 仍是 old
        self.user.email = "old@163.com"
        self.user.save()
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_APPROVED, identifier="old@163.com",
        )
        resp = _bind(self._client(), "new@163.com")
        self.assertEqual(resp.status_code, 200, resp.content)
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        self.assertEqual(v.identifier, "new@163.com")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@163.com")  # 旧邮箱仍有效

    def test_bind_same_approved_email_is_noop(self):
        # 已验证同邮箱再绑：保持 approved（不降级为 pending）
        self.user.email = "same@163.com"
        self.user.save()
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_APPROVED, identifier="same@163.com",
        )
        resp = _bind(self._client(), "same@163.com")
        self.assertEqual(resp.status_code, 200)
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.status, Verification.STATUS_APPROVED)
        self.assertEqual(len(mail.outbox), 0)  # 已验证，不重发

    def test_change_email_verify_promotes_new(self):
        self.user.email = "old@163.com"
        self.user.save()
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_APPROVED, identifier="old@163.com",
        )
        _bind(self._client(), "new@163.com")
        # 点新邮箱的验证链接
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = email_verification_token.make_token(self.user)
        resp = Client().get(f"/auth/verify-email/?uid={uid}&token={token}")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@163.com")  # 晋升为新邮箱


class EmailLoginTest(TestCase):
    """邮箱登录只认 User.email（已绑定）；待验邮箱登不进。"""

    def setUp(self):
        cache.clear()

    def test_pending_email_cannot_login(self):
        # 待验邮箱住 identifier、不进 User.email → 邮箱登录无匹配 → 凭据无效
        u = User.objects.create_user(username="u", password="StrongPass123!", is_active=True)
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING, identifier="pending@163.com",
        )
        resp = _login(Client(), email="pending@163.com", password="StrongPass123!")
        self.assertEqual(resp.status_code, 401)

    def test_bound_email_can_login(self):
        make_approved_email_user("u", "bound@163.com", "StrongPass123!")
        resp = _login(Client(), email="bound@163.com", password="StrongPass123!")
        self.assertEqual(resp.status_code, 200)


class PasswordResetRequiresBoundEmailTest(TestCase):
    """密码重置按 User.email（已验证绑定）发链接；无绑定邮箱不发。"""

    def setUp(self):
        cache.clear()

    def test_reset_for_bound_email_sends_link(self):
        make_approved_email_user("u", "bound@163.com", "oldsecret123")
        resp = Client().post(
            "/auth/password-reset/",
            data=json.dumps({"email": "bound@163.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_for_pending_email_sends_nothing(self):
        # 待验邮箱不在 User.email → 无匹配账号 → 不发重置链接（防未验证邮箱重置）
        u = User.objects.create_user(username="u", password="p", is_active=True)
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING, identifier="pending@163.com",
        )
        Client().post(
            "/auth/password-reset/",
            data=json.dumps({"email": "pending@163.com"}),
            content_type="application/json",
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_no_leak_for_unknown(self):
        resp = Client().post(
            "/auth/password-reset/",
            data=json.dumps({"email": "nobody@163.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)  # 提示一致（防枚举）
        self.assertEqual(len(mail.outbox), 0)
