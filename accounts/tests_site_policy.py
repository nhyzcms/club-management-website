"""Site policy gates: verification_closed / registration_closed + throttle from snapshot."""
import json

from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.admin import ProfileAdmin, approve_identity, disable_account, reject_identity
from accounts.models import IdentityProof, Profile, Verification, is_verified
from accounts.permissions import IsVerified
from accounts.test_helpers import grant_verification
from accounts.tokens import email_verification_token
from common.models import SiteSettings
from common.policy import get_policy
from rest_framework.test import APIRequestFactory


PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cf00000003000100184bbb6e0000000049454e44ae426082"
)


def set_policy(**kwargs):
    obj, _ = SiteSettings.objects.get_or_create(pk=1)
    for key, value in kwargs.items():
        setattr(obj, key, value)
    obj.save()
    return obj


class _PolicyTestCase(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()


def grant_review(user):
    user.user_permissions.add(Permission.objects.get(codename="can_review_identity"))
    return User.objects.get(pk=user.pk)


class VerificationClosedTest(_PolicyTestCase):
    def setUp(self):
        super().setUp()
        set_policy(verification_enabled=False)
        self.user = User.objects.create_user(username="u", password="p", is_active=True)
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING, identifier="u@163.com",
        )

    def _client(self):
        c = Client()
        c.force_login(self.user)
        return c

    def test_bind_forbidden(self):
        # 邮箱用白名单内域名：确保 403 来自「通道关闭」而非后缀白名单
        resp = self._client().post(
            "/auth/verification/email/bind/",
            data=json.dumps({"email": "new@163.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "verification_closed")
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.identifier, "u@163.com")  # unchanged

    def test_resend_forbidden(self):
        resp = Client().post(
            "/auth/resend-verification/",
            data=json.dumps({"email": "u@163.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "verification_closed")
        self.assertEqual(len(mail.outbox), 0)

    def test_verify_link_forbidden_leaves_pending(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = email_verification_token.make_token(self.user)
        resp = Client().get(f"/auth/verify-email/?uid={uid}&token={token}")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "verification_closed")
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")

    def test_manual_submit_forbidden(self):
        proof = SimpleUploadedFile("p.png", PNG_BYTES, content_type="image/png")
        resp = self._client().post(
            "/auth/verification/manual/submit/",
            data={"real_name": "李四", "identity": "student", "proof_files": proof},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "verification_closed")
        self.assertFalse(
            Verification.objects.filter(
                user=self.user, channel=Verification.CHANNEL_MANUAL,
            ).exists()
        )
        self.assertEqual(IdentityProof.objects.filter(user=self.user).count(), 0)

    def test_register_skips_email_pending_row(self):
        resp = Client().post("/auth/register/", data={
            "username": "newbie",
            "password": "StrongPass123!",
            "password2": "StrongPass123!",
            "real_name": "张三",
            "identity": "student",
            "email": "newbie@163.com",
            "turnstile_token": "dummy",
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        user = User.objects.get(username="newbie")
        self.assertEqual(Verification.objects.filter(user=user).count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(is_verified(user))

    def test_is_verified_unchanged(self):
        self.assertFalse(is_verified(self.user))
        approved = User.objects.create_user(username="ok", password="p")
        Verification.objects.create(
            user=approved, channel=Verification.CHANNEL_MANUAL,
            status=Verification.STATUS_APPROVED,
        )
        self.assertTrue(is_verified(approved))
        req = APIRequestFactory().post("/")
        req.user = self.user
        self.assertFalse(IsVerified().has_permission(req, None))
        req.user = approved
        self.assertTrue(IsVerified().has_permission(req, None))


class AdminReviewBlockedWhenClosedTest(_PolicyTestCase):
    def setUp(self):
        super().setUp()
        set_policy(verification_enabled=False)
        self.reviewer = grant_review(User.objects.create_user(username="rev", password="p"))
        self.target = User.objects.create_user(username="tgt", password="p", email="t@e.com")
        Profile.objects.create(user=self.target)
        Verification.objects.create(
            user=self.target, channel=Verification.CHANNEL_MANUAL,
            status=Verification.STATUS_PENDING,
        )
        self.factory = RequestFactory()
        self.ma = ProfileAdmin(Profile, admin.site)
        self.ma.message_user = lambda *a, **k: None

    def _req(self):
        req = self.factory.post("/")
        req.user = self.reviewer
        return req

    def test_approve_is_noop(self):
        approve_identity(self.ma, self._req(), Profile.objects.filter(pk=self.target.profile.pk))
        v = Verification.objects.get(user=self.target, channel=Verification.CHANNEL_MANUAL)
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        self.assertFalse(is_verified(self.target))
        self.assertEqual(len(mail.outbox), 0)

    def test_reject_is_noop(self):
        reject_identity(self.ma, self._req(), Profile.objects.filter(pk=self.target.profile.pk))
        v = Verification.objects.get(user=self.target, channel=Verification.CHANNEL_MANUAL)
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        self.assertEqual(len(mail.outbox), 0)

    def test_disable_account_still_works(self):
        disable_account(self.ma, self._req(), Profile.objects.filter(pk=self.target.profile.pk))
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)


class RegistrationClosedTest(_PolicyTestCase):
    def setUp(self):
        super().setUp()
        set_policy(registration_enabled=False)

    def test_register_forbidden(self):
        resp = Client().post("/auth/register/", data={
            "username": "newbie",
            "password": "StrongPass123!",
            "password2": "StrongPass123!",
            "turnstile_token": "dummy",
        })
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "registration_closed")
        self.assertFalse(User.objects.filter(username="newbie").exists())


class RegisterThrottleFromPolicyTest(_PolicyTestCase):
    def setUp(self):
        super().setUp()
        set_policy(register_per_ip_per_day=1)

    def test_lowered_limit_blocks_second_attempt(self):
        self.assertEqual(get_policy().register_per_ip_per_day, 1)
        first = Client().post("/auth/register/", data={})
        self.assertEqual(first.status_code, 400)
        second = Client().post("/auth/register/", data={})
        self.assertEqual(second.status_code, 429)


class CommentsDmsGateTest(_PolicyTestCase):
    """评论区 / 私信开关（站点策略）：关闭时写操作 403、读保留；默认开启行为不变。"""

    def setUp(self):
        super().setUp()
        self.user = grant_verification(User.objects.create_user(username="gate", password="x"))
        self.client = Client()
        self.client.force_login(self.user)

    def _post(self, path, payload):
        return self.client.post(path, data=json.dumps(payload), content_type="application/json")

    def test_policy_snapshot_exposes_switches(self):
        policy = get_policy()
        self.assertTrue(policy.comments_enabled)
        self.assertTrue(policy.dms_enabled)
        set_policy(comments_enabled=False, dms_enabled=False)
        policy = get_policy()
        self.assertFalse(policy.comments_enabled)
        self.assertFalse(policy.dms_enabled)

    def test_comment_create_forbidden_when_disabled(self):
        set_policy(comments_enabled=False)
        resp = self._post("/messaging/comments/", {"thread": 1})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "评论功能已关闭")

    def test_comment_create_passes_gate_when_enabled(self):
        # 默认开启：闸门放行，进入既有校验（thread 不存在 → 404，证明未被 403 拦截）
        resp = self._post("/messaging/comments/", {"thread": 1})
        self.assertEqual(resp.status_code, 404)

    def test_send_dm_forbidden_when_disabled(self):
        set_policy(dms_enabled=False)
        resp = self._post("/messaging/conversations/999/send_message/", {"content": "hi"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "私信功能已关闭")

    def test_send_dm_passes_gate_when_enabled(self):
        # 默认开启：闸门放行，进入对象查找（会话不存在 → 404，证明未被 403 拦截）
        resp = self._post("/messaging/conversations/999/send_message/", {"content": "hi"})
        self.assertEqual(resp.status_code, 404)

    def test_start_private_forbidden_when_disabled(self):
        set_policy(dms_enabled=False)
        resp = self._post("/messaging/conversations/start_private/", {"user_id": 1})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "私信功能已关闭")
