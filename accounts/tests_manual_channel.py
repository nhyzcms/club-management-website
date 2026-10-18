"""人工审批通道端到端（#38）：提交身份证明 / 通过·驳回·停用 / 驳回后重交 / 权限门禁。

提交走 HTTP（面板动作）；通过 / 驳回 / 停用走 identity_review 服务（admin 批量动作与
``/auth/identity-reviews/`` API 共用）。本文件测提交 + admin 动作；API 见 tests_identity_review。
证明材料（IdentityProof）永久留底、累加，审核通过后亦不删（审计）。
"""
from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase

from accounts.admin import ProfileAdmin, approve_identity, disable_account, reject_identity
from accounts.models import IdentityProof, Profile, Verification, is_verified

SUBMIT = "/auth/verification/manual/submit/"

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cf00000003000100184bbb6e0000000049454e44ae426082"
)


def proof(name="proof.png", content_type="image/png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type=content_type)


def grant_review(user):
    user.user_permissions.add(Permission.objects.get(codename="can_review_identity"))
    return User.objects.get(pk=user.pk)  # 刷新权限缓存


class ManualSubmitTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p", is_active=True)
        self.reviewer = grant_review(User.objects.create_user(username="rev", password="p"))
        self.target = User.objects.create_user(username="tgt", password="p", email="t@e.com")
        Profile.objects.create(user=self.target)
        self.factory = RequestFactory()
        self.ma = ProfileAdmin(Profile, admin.site)
        self.ma.message_user = lambda *a, **k: None

    def _client(self):
        c = Client()
        c.force_login(self.user)
        return c

    def _submit(self, client, *, real_name="李四", identity="student", files=None):
        fs = files if files is not None else [proof()]
        data = {"real_name": real_name, "identity": identity, "proof_files": fs if isinstance(fs, list) else [fs]}
        return client.post(SUBMIT, data=data)

    # ---- 提交 ----
    def test_submit_creates_pending_channel_and_proof(self):
        resp = self._submit(self._client())
        self.assertEqual(resp.status_code, 200, resp.content)
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_MANUAL)
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        self.assertEqual(IdentityProof.objects.filter(user=self.user).count(), 1)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.real_name, "李四")
        self.assertFalse(is_verified(self.user))  # pending 不算已认证

    def test_submit_multiple_proofs_accumulate(self):
        resp = self._submit(self._client(), files=[proof(), proof("p2.png"), proof("p3.png")])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(IdentityProof.objects.filter(user=self.user).count(), 3)

    def test_submit_requires_login(self):
        self.assertEqual(self._submit(Client()).status_code, 302)

    def test_submit_requires_real_name(self):
        c = self._client()
        resp = c.post(SUBMIT, data={"real_name": "", "identity": "student", "proof_files": proof()})
        self.assertEqual(resp.status_code, 400)

    def test_submit_requires_identity(self):
        c = self._client()
        resp = c.post(SUBMIT, data={"real_name": "李四", "proof_files": proof()})  # 无 identity
        self.assertEqual(resp.status_code, 400)

    def test_submit_rejects_invalid_identity(self):
        c = self._client()
        resp = self._submit(c, identity="alien")
        self.assertEqual(resp.status_code, 400)

    def test_submit_accepts_parent_and_teacher(self):
        for ident in ("parent", "teacher"):
            user = User.objects.create_user(username=f"u_{ident}", password="p")
            c = Client()
            c.force_login(user)
            resp = self._submit(c, real_name="测", identity=ident)
            self.assertEqual(resp.status_code, 200, f"{ident} 应被接受: {resp.content}")
            self.assertEqual(User.objects.get(username=f"u_{ident}").profile.identity, ident)

    def test_submit_requires_proof(self):
        c = self._client()
        resp = c.post(SUBMIT, data={"real_name": "李四"})  # 无 proof_files
        self.assertEqual(resp.status_code, 400)

    def test_submit_too_many_proofs_rejected(self):
        c = self._client()
        resp = c.post(SUBMIT, data={"real_name": "李四", "proof_files": [proof(f"p{i}.png") for i in range(4)]})
        self.assertEqual(resp.status_code, 400)

    def test_submit_oversize_proof_rejected(self):
        big = SimpleUploadedFile("big.png", b"x" * (5 * 1024 * 1024 + 1), content_type="image/png")
        c = self._client()
        resp = c.post(SUBMIT, data={"real_name": "李四", "proof_files": big})
        self.assertEqual(resp.status_code, 400)

    def test_submit_wrong_content_type_rejected(self):
        bad = SimpleUploadedFile("proof.txt", b"not an image", content_type="text/plain")
        c = self._client()
        resp = c.post(SUBMIT, data={"real_name": "李四", "proof_files": bad})
        self.assertEqual(resp.status_code, 400)

    def test_submit_while_pending_rejected(self):
        Verification.objects.create(user=self.user, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_PENDING)
        resp = self._submit(self._client())
        self.assertEqual(resp.status_code, 400)  # 审核中，不可重复提交

    def test_submit_while_approved_rejected(self):
        Verification.objects.create(user=self.user, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_APPROVED)
        resp = self._submit(self._client())
        self.assertEqual(resp.status_code, 400)  # 已通过

    # ---- admin 动作 ----
    def _req(self, user):
        req = self.factory.post("/")
        req.user = user
        return req

    def test_approve_sets_manual_approved(self):
        Verification.objects.create(user=self.target, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_PENDING)
        approve_identity(self.ma, self._req(self.reviewer), Profile.objects.filter(pk=self.target.profile.pk))
        v = Verification.objects.get(user=self.target, channel=Verification.CHANNEL_MANUAL)
        self.assertEqual(v.status, Verification.STATUS_APPROVED)
        self.assertEqual(v.verified_by, self.reviewer)
        self.assertTrue(is_verified(self.target))
        from messaging.models import Notification

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.target, category="review", event="identity_resolved",
            ).exists()
        )

    def test_reject_sets_manual_rejected_and_emails(self):
        Verification.objects.create(user=self.target, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_PENDING)
        reject_identity(self.ma, self._req(self.reviewer), Profile.objects.filter(pk=self.target.profile.pk))
        v = Verification.objects.get(user=self.target, channel=Verification.CHANNEL_MANUAL)
        self.assertEqual(v.status, Verification.STATUS_REJECTED)
        self.assertFalse(is_verified(self.target))
        from messaging.models import Notification

        n = Notification.objects.filter(
            recipient=self.target, category="review", event="identity_resolved",
        ).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.payload.get("result"), "rejected")

    def test_disable_sets_inactive(self):
        Verification.objects.create(user=self.target, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_PENDING)
        disable_account(self.ma, self._req(self.reviewer), Profile.objects.filter(pk=self.target.profile.pk))
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

    def test_actions_hidden_without_perm(self):
        actions = self.ma.get_actions(self._req(User.objects.create_user(username="staff", password="p")))
        self.assertNotIn("approve_identity", actions)
        self.assertNotIn("reject_identity", actions)
        self.assertNotIn("disable_account", actions)

    def test_actions_shown_with_perm(self):
        actions = self.ma.get_actions(self._req(self.reviewer))
        self.assertIn("approve_identity", actions)
        self.assertIn("reject_identity", actions)
        self.assertIn("disable_account", actions)

    # ---- 驳回后重交（端到端）----
    def test_resubmit_after_reject_returns_pending_and_keeps_old_proof(self):
        c = self._client()
        # 首次提交
        self._submit(c, files=[proof("first.png")])
        # admin 驳回
        reject_identity(self.ma, self._req(self.reviewer), Profile.objects.filter(pk=self.user.profile.pk))
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_MANUAL)
        self.assertEqual(v.status, Verification.STATUS_REJECTED)
        # 重交
        resp = self._submit(c, real_name="李四新", files=[proof("second.png")])
        self.assertEqual(resp.status_code, 200, resp.content)
        v.refresh_from_db()
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        # 旧证明永久留底 + 新证明累加 → 共 2 条
        self.assertEqual(IdentityProof.objects.filter(user=self.user).count(), 2)
