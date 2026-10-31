"""人工通道审核 API（/auth/identity-reviews/）：HTTP 公共接口，不测内部结构。

Seams：
- ``GET /auth/identity-reviews/?status=``：审核员 200，他人 403；默认 pending；一用户一行
- ``POST .../{id}/approve|reject|disable/``：与 admin 动作同语义（mail / 会话吊销 / 政策门禁）
- ``GET /auth/me/``：``can_review_identity`` 能力投影
"""
from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import IdentityProof, Profile, UserSession, Verification, is_verified
from common.models import SiteSettings


PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489000000"
    "0d49444154789c6360606060000000050001a5f645400000000049454e44ae426082"
)

LIST = "/auth/identity-reviews/"
SUBMIT = "/auth/verification/manual/submit/"


def grant_review(user):
    user.user_permissions.add(Permission.objects.get(codename="can_review_identity"))
    return User.objects.get(pk=user.pk)


def set_policy(**kwargs):
    obj, _ = SiteSettings.objects.get_or_create(pk=1)
    for key, value in kwargs.items():
        setattr(obj, key, value)
    obj.save()
    return obj


def _proof(name="p.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


class IdentityReviewApiTest(TestCase):
    def setUp(self):
        cache.clear()
        self.reviewer = grant_review(User.objects.create_user(username="rev", password="p"))
        self.other = User.objects.create_user(username="other", password="p")
        self.target = User.objects.create_user(username="tgt", password="p", email="t@e.com")
        Profile.objects.create(user=self.target, real_name="李四", identity="student")
        self.v = Verification.objects.create(
            user=self.target, channel=Verification.CHANNEL_MANUAL,
            status=Verification.STATUS_PENDING,
        )
        self.p1 = IdentityProof.objects.create(user=self.target, file=_proof("a.png"))
        self.p2 = IdentityProof.objects.create(user=self.target, file=_proof("b.png"))
        self.client = APIClient()
        self.client.force_authenticate(self.reviewer)

    def tearDown(self):
        cache.clear()

    def test_reviewer_lists_pending(self):
        resp = self.client.get(LIST)
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], self.v.pk)
        self.assertEqual(row["username"], "tgt")
        self.assertEqual(row["real_name"], "李四")
        self.assertEqual(row["identity"], "student")
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["verified_at"])
        self.assertIsNone(row["verified_by"])
        proof_ids = {p["id"] for p in row["proofs"]}
        self.assertEqual(proof_ids, {self.p1.pk, self.p2.pk})
        urls = {p["url"] for p in row["proofs"]}
        self.assertEqual(
            urls,
            {f"/auth/identity-proof/{self.p1.pk}/", f"/auth/identity-proof/{self.p2.pk}/"},
        )

    def test_default_status_is_pending(self):
        Verification.objects.create(
            user=User.objects.create_user(username="ok", password="p"),
            channel=Verification.CHANNEL_MANUAL,
            status=Verification.STATUS_APPROVED,
        )
        resp = self.client.get(LIST)
        self.assertEqual([r["id"] for r in resp.data["results"]], [self.v.pk])

    def test_status_filter_approved(self):
        self.v.status = Verification.STATUS_APPROVED
        self.v.save(update_fields=["status"])
        resp = self.client.get(LIST + "?status=approved")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r["id"] for r in resp.data["results"]], [self.v.pk])
        self.assertEqual(self.client.get(LIST).data["results"], [])

    def test_list_excludes_email_channel(self):
        email_user = User.objects.create_user(username="mail", password="p")
        email_v = Verification.objects.create(
            user=email_user, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING, identifier="m@e.com",
        )
        ids = [r["id"] for r in self.client.get(LIST).data["results"]]
        self.assertNotIn(email_v.pk, ids)

    def test_other_user_forbidden(self):
        client = APIClient()
        client.force_authenticate(self.other)
        self.assertEqual(client.get(LIST).status_code, 403)
        self.assertEqual(
            client.post(f"{LIST}{self.v.pk}/approve/").status_code, 403,
        )

    def test_approve_sets_manual_approved_and_emails(self):
        resp = self.client.post(f"{LIST}{self.v.pk}/approve/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "approved")
        self.assertEqual(resp.data["verified_by"]["id"], self.reviewer.pk)
        self.assertIsNotNone(resp.data["verified_at"])
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, Verification.STATUS_APPROVED)
        self.assertEqual(self.v.verified_by, self.reviewer)
        self.assertTrue(is_verified(self.target))
        from messaging.models import Notification

        n = Notification.objects.filter(
            recipient=self.target, category="review", event="identity_resolved",
        ).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.payload.get("result"), "approved")

    def test_reject_sets_rejected_and_allows_resubmit(self):
        resp = self.client.post(f"{LIST}{self.v.pk}/reject/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "rejected")
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, Verification.STATUS_REJECTED)
        self.assertFalse(is_verified(self.target))
        from messaging.models import Notification

        n = Notification.objects.filter(
            recipient=self.target, category="review", event="identity_resolved",
        ).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.payload.get("result"), "rejected")

        submitter = APIClient()
        submitter.force_login(self.target)
        resubmit = submitter.post(
            SUBMIT,
            data={"real_name": "李四新", "identity": "student", "proof_files": _proof("c.png")},
        )
        self.assertEqual(resubmit.status_code, 200, resubmit.content)
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, Verification.STATUS_PENDING)

    def test_disable_revokes_sessions(self):
        key = "x" * 40
        Session.objects.create(
            session_key=key, session_data="x",
            expire_date=timezone.now() + timedelta(days=1),
        )
        UserSession.objects.create(user=self.target, session_key=key)
        resp = self.client.post(f"{LIST}{self.v.pk}/disable/")
        self.assertEqual(resp.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertIsNotNone(UserSession.objects.get(user=self.target, session_key=key).revoked_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("停用", mail.outbox[0].subject)


class IdentityReviewPolicyClosedTest(TestCase):
    def setUp(self):
        cache.clear()
        set_policy(verification_enabled=False)
        self.reviewer = grant_review(User.objects.create_user(username="rev", password="p"))
        self.target = User.objects.create_user(username="tgt", password="p", email="t@e.com")
        Profile.objects.create(user=self.target)
        self.v = Verification.objects.create(
            user=self.target, channel=Verification.CHANNEL_MANUAL,
            status=Verification.STATUS_PENDING,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.reviewer)

    def tearDown(self):
        cache.clear()

    def test_approve_forbidden(self):
        resp = self.client.post(f"{LIST}{self.v.pk}/approve/")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["reason"], "verification_closed")
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, Verification.STATUS_PENDING)
        self.assertEqual(len(mail.outbox), 0)

    def test_reject_forbidden(self):
        resp = self.client.post(f"{LIST}{self.v.pk}/reject/")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["reason"], "verification_closed")
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, Verification.STATUS_PENDING)
        self.assertEqual(len(mail.outbox), 0)

    def test_disable_still_works(self):
        resp = self.client.post(f"{LIST}{self.v.pk}/disable/")
        self.assertEqual(resp.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)


class IdentityReviewCapabilityTest(TestCase):
    def test_me_exposes_can_review_identity(self):
        user = grant_review(User.objects.create_user(username="rev", password="p"))
        client = APIClient()
        client.force_login(user)
        perms = client.get("/auth/me/").json()["user"]["permissions"]
        self.assertTrue(perms["can_review_identity"])

    def test_plain_user_capability_false(self):
        user = User.objects.create_user(username="plain", password="p")
        client = APIClient()
        client.force_login(user)
        perms = client.get("/auth/me/").json()["user"]["permissions"]
        self.assertFalse(perms["can_review_identity"])

    def test_president_group_can_list(self):
        user = User.objects.create_user(username="pres", password="p")
        user.groups.add(Group.objects.get(name="社长"))
        user = User.objects.get(pk=user.pk)
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.get(LIST).status_code, 200)
        self.assertTrue(user.has_perm("accounts.can_review_identity"))
