"""admin 身份审核台（#31）：证明鉴权下载 + 通过/停用 action + 动作权限收口。"""
from datetime import timedelta

from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.contrib.sessions.models import Session
from django.core import mail
from django.test import RequestFactory, TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from accounts.models import IdentityProof, Profile, UserSession, Verification, is_verified
from accounts.admin import CustomUserAdmin, IdentityProofAdmin, ProfileAdmin, approve_identity, disable_account

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cf00000003000100184bbb6e0000000049454e44ae426082"
)


def grant_review(user):
    user.user_permissions.add(Permission.objects.get(codename="can_review_identity"))
    return User.objects.get(pk=user.pk)  # 刷新，避免本实例权限缓存过期


class IdentityProofDownloadViewTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="p", email="o@e.com")
        self.other = User.objects.create_user(username="other", password="p")
        self.reviewer = grant_review(User.objects.create_user(username="rev", password="p"))
        self.proof = IdentityProof.objects.create(
            user=self.owner, file=SimpleUploadedFile("p.png", PNG_BYTES, content_type="image/png")
        )

    def test_owner_can_download(self):
        c = self._client(self.owner)
        resp = c.get(f"/auth/identity-proof/{self.proof.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.streaming)  # FileResponse 流式

    def test_reviewer_can_download(self):
        c = self._client(self.reviewer)
        self.assertEqual(c.get(f"/auth/identity-proof/{self.proof.pk}/").status_code, 200)

    def test_other_user_forbidden(self):
        c = self._client(self.other)
        self.assertEqual(c.get(f"/auth/identity-proof/{self.proof.pk}/").status_code, 403)

    def test_anonymous_redirected_to_login(self):
        from django.test import Client
        self.assertEqual(Client().get(f"/auth/identity-proof/{self.proof.pk}/").status_code, 302)

    def test_missing_file_404(self):
        # 物理文件被删 → 404（非 500）
        path = self.proof.file.path
        self.proof.file.storage.delete(self.proof.file.name)
        c = self._client(self.owner)
        self.assertEqual(c.get(f"/auth/identity-proof/{self.proof.pk}/").status_code, 404)

    def _client(self, user):
        from django.test import Client
        c = Client()
        c.force_login(user)
        return c


class AdminReviewActionsTest(TestCase):
    def setUp(self):
        self.reviewer = grant_review(User.objects.create_user(username="rev", password="p"))
        self.staff_no_perm = User.objects.create_user(username="staff", password="p")
        self.target = User.objects.create_user(username="tgt", password="p", email="t@e.com")
        Profile.objects.create(user=self.target)  # 审核动作挂在 ProfileAdmin，需有 profile
        self.factory = RequestFactory()
        self.ma = ProfileAdmin(Profile, admin.site)
        # message_user 依赖 messages 中间件；RequestFactory 裸请求没有，stub 掉（动作逻辑不受影响）
        self.ma.message_user = lambda *a, **k: None

    def _req(self, user):
        req = self.factory.post("/")
        req.user = user
        return req

    def test_approve_sets_manual_channel_approved_and_emails(self):
        approve_identity(self.ma, self._req(self.reviewer), Profile.objects.filter(pk=self.target.profile.pk))
        v = Verification.objects.get(user=self.target, channel=Verification.CHANNEL_MANUAL)
        self.assertEqual(v.status, Verification.STATUS_APPROVED)
        self.assertEqual(v.verified_by, self.reviewer)
        self.assertIsNotNone(v.verified_at)
        self.assertTrue(is_verified(self.target))  # manual approved ⇒ 已认证
        from messaging.models import Notification

        n = Notification.objects.filter(
            recipient=self.target, category="review", event="identity_resolved",
        ).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.payload.get("result"), "approved")
        self.assertEqual(len(mail.outbox), 0)  # 默认仅站内订阅（邮件需用户开启）

    def test_disable_account_sets_inactive_and_emails(self):
        disable_account(self.ma, self._req(self.reviewer), Profile.objects.filter(pk=self.target.profile.pk))
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("停用", mail.outbox[0].subject)

    def test_disable_account_revokes_active_sessions(self):
        # 停用应立即吊销既有会话，否则被停用账号仍可用当前会话直到过期
        key = "x" * 40
        Session.objects.create(session_key=key, session_data="x",
                               expire_date=timezone.now() + timedelta(days=1))
        UserSession.objects.create(user=self.target, session_key=key)
        disable_account(self.ma, self._req(self.reviewer), Profile.objects.filter(pk=self.target.profile.pk))
        self.assertFalse(Session.objects.filter(session_key=key).exists())  # 强制登出
        self.assertIsNotNone(UserSession.objects.get(user=self.target, session_key=key).revoked_at)

    def test_get_actions_hidden_without_perm(self):
        # 无 can_review_identity 的 staff 看不到审核动作
        actions = self.ma.get_actions(self._req(self.staff_no_perm))
        self.assertNotIn("approve_identity", actions)
        self.assertNotIn("disable_account", actions)

    def test_get_actions_shown_with_perm(self):
        actions = self.ma.get_actions(self._req(self.reviewer))
        self.assertIn("approve_identity", actions)
        self.assertIn("disable_account", actions)


class IdentityProofAdminListTest(TestCase):
    """审核通过后证明列表能看出人工通道状态；缩略图可点开大图。"""

    def setUp(self):
        self.reviewer = grant_review(User.objects.create_user(username="rev", password="p"))
        self.target = User.objects.create_user(username="tgt", password="p", email="t@e.com")
        Profile.objects.create(user=self.target)
        self.proof = IdentityProof.objects.create(
            user=self.target, file=SimpleUploadedFile("p.png", PNG_BYTES, content_type="image/png")
        )
        Verification.objects.create(
            user=self.target, channel=Verification.CHANNEL_MANUAL,
            status=Verification.STATUS_PENDING,
        )
        self.factory = RequestFactory()
        self.profile_admin = ProfileAdmin(Profile, admin.site)
        self.profile_admin.message_user = lambda *a, **k: None
        self.proof_admin = IdentityProofAdmin(IdentityProof, admin.site)

    def _req(self, user):
        req = self.factory.post("/")
        req.user = user
        return req

    def test_list_shows_manual_status_after_approve(self):
        req = self.factory.get("/")
        req.user = self.reviewer
        obj = self.proof_admin.get_queryset(req).get(pk=self.proof.pk)
        self.assertEqual(self.proof_admin.manual_channel_status(obj), "待认证")

        approve_identity(
            self.profile_admin, self._req(self.reviewer),
            Profile.objects.filter(pk=self.target.profile.pk),
        )
        obj = self.proof_admin.get_queryset(req).get(pk=self.proof.pk)
        self.assertEqual(self.proof_admin.manual_channel_status(obj), "已通过")

    def test_thumb_is_larger_and_links_to_proof_image(self):
        html = str(self.proof_admin.proof_thumb(self.proof))
        self.assertIn("240px", html)
        self.assertIn(f"/auth/identity-proof/{self.proof.pk}/", html)
        self.assertIn("<a ", html)


class UserAdminBanMuteTest(TestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser("adm", "a@e.com", "x")
        self.staff = User.objects.create_user(username="staff", password="p")
        self.target = User.objects.create_user(username="tgt", password="p", email="t@e.com")
        self.other = User.objects.create_user(username="other", password="p")
        self.factory = RequestFactory()
        self.ma = CustomUserAdmin(User, admin.site)
        self.ma.message_user = lambda *a, **k: None

    def _req(self, user):
        req = self.factory.post("/")
        req.user = user
        return req

    def test_ban_disables_and_skips_self_and_superuser(self):
        qs = User.objects.filter(pk__in=[self.target.pk, self.actor.pk])
        self.ma.ban_users(self._req(self.actor), qs)
        self.target.refresh_from_db()
        self.actor.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertTrue(self.actor.is_active)

    def test_mute_action_hidden_without_perm(self):
        actions = self.ma.get_actions(self._req(self.staff))
        self.assertNotIn("mute_users", actions)

    def test_mute_creates_site_mute(self):
        self.actor.user_permissions.add(
            Permission.objects.get(content_type__app_label="messaging", codename="mute_user"),
        )
        self.actor = User.objects.get(pk=self.actor.pk)
        from messaging.services import is_muted
        self.ma.mute_users(self._req(self.actor), User.objects.filter(pk=self.target.pk))
        self.assertTrue(is_muted(self.target))

    def test_mute_skips_self(self):
        self.actor.user_permissions.add(
            Permission.objects.get(content_type__app_label="messaging", codename="mute_user"),
        )
        self.actor = User.objects.get(pk=self.actor.pk)
        from messaging.services import is_muted
        self.ma.mute_users(self._req(self.actor), User.objects.filter(pk=self.actor.pk))
        self.assertFalse(is_muted(self.actor))

    def test_changelist_shows_ban_and_mute(self):
        from django.test import Client
        c = Client()
        c.force_login(self.actor)
        resp = c.get("/admin/auth/user/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "封禁")
        self.assertContains(resp, "全站禁言")
