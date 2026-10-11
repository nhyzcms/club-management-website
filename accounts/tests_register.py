"""注册（ADR-0006 注册↔验证分离，2026-09 修订）：建登录身份（用户名 + 密码 + Turnstile）
+ 真实姓名 / 身份（必填，写入 Profile），邮箱可选。

覆盖：最小注册建 User+Profile（无 Verification 行 ⇒ 访客）；带邮箱注册建 email 通道 pending
并发验证信（User.email 保持空）；必填 real_name/identity；用户名/邮箱唯一；密码校验；
注册限流；Turnstile 接线；证明材料落私有存储（IdentityProof 在 #38 人工通道经 ORM 造）。

用例邮箱统一用白名单内域名（@163.com），否则会被后缀白名单拦下（见 tests_email_domain / ADR-0023）。
"""
from pathlib import Path

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import IdentityProof, Verification, is_verified

# 1x1 透明 PNG（合法图片，Pillow 可读）。
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cf00000003000100184bbb6e0000000049454e44ae426082"
)


def proof(name="proof.png", content_type="image/png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type=content_type)


def valid_payload(**overrides):
    """一份合法注册 payload（multipart）：用户名 + 双密码 + 真实姓名 + 身份 + Turnstile 必填。"""
    files = overrides.pop("proof_files", None)  # 注册不再要证明；保留参数兼容旧调用
    base = {
        "username": "newbie",
        "password": "StrongPass123!",
        "password2": "StrongPass123!",
        "real_name": "张三",
        "identity": "student",
        "turnstile_token": "dummy",
    }
    base.update(overrides)
    return base


class RegisterViewTest(TestCase):
    def setUp(self):
        cache.clear()  # 注册限流按 IP 计数；隔离每个用例。

    def post(self, fields):
        return self.client.post("/auth/register/", data=fields)

    # ---- 最小注册（无邮箱）----
    def test_register_minimal_success_no_email(self):
        resp = self.post(valid_payload())
        self.assertEqual(resp.status_code, 201, resp.content)

        user = User.objects.get(username="newbie")
        self.assertEqual(user.email, "")  # 无邮箱 → User.email 空（只装已验证邮箱）
        self.assertTrue(user.is_active)
        # 新号无 Verification 行 ⇒ 未验证（访客）
        self.assertEqual(Verification.objects.filter(user=user).count(), 0)
        self.assertFalse(is_verified(user))
        # 无邮箱不发信
        self.assertEqual(len(mail.outbox), 0)

    def test_register_creates_profile_without_legacy_verification_fields(self):
        self.post(valid_payload())
        user = User.objects.get(username="newbie")
        # Profile 存在；验证态不在 Profile 上（已删四字段）
        self.assertTrue(user.profile)
        for gone in ("email_verified", "identity_verified", "verified_at", "verified_by"):
            self.assertFalse(hasattr(user.profile, gone))

    # ---- 带邮箱注册：建 email 通道 pending + 发信，User.email 不动 ----
    def test_register_with_email_starts_email_verification(self):
        resp = self.post(valid_payload(email="newbie@163.com"))
        self.assertEqual(resp.status_code, 201, resp.content)

        user = User.objects.get(username="newbie")
        self.assertEqual(user.email, "")  # 待验邮箱不住 User.email
        v = Verification.objects.get(user=user, channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        self.assertEqual(v.identifier, "newbie@163.com")
        # 仅 email 通道 pending（未 approved）⇒ 仍未验证
        self.assertFalse(is_verified(user))
        # 验证信发往待验地址
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("newbie@163.com", mail.outbox[0].to)
        self.assertIn("/#/verify-email?uid=", mail.outbox[0].body)

    def test_register_email_normalized_lowercase(self):
        self.post(valid_payload(email="Newbie@163.COM"))
        v = Verification.objects.get(user__username="newbie", channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.identifier, "newbie@163.com")

    # ---- 真实姓名 / 身份（必填）----
    def test_real_name_identity_stored_on_profile(self):
        self.post(valid_payload(real_name="李四", identity="teacher"))
        user = User.objects.get(username="newbie")
        self.assertEqual(user.profile.real_name, "李四")
        self.assertEqual(user.profile.identity, "teacher")

    def test_register_requires_real_name(self):
        resp = self.post(valid_payload(real_name=""))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("真实姓名", str(resp.json()["error"]))
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_register_requires_real_name_not_just_spaces(self):
        # 空白串 strip 后为空 → 同样拒绝
        resp = self.post(valid_payload(real_name="   "))
        self.assertEqual(resp.status_code, 400)

    def test_register_requires_identity(self):
        resp = self.post(valid_payload(identity=""))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("身份", str(resp.json()["error"]))
        self.assertFalse(User.objects.filter(username="newbie").exists())

    # ---- 唯一性 ----
    def test_duplicate_username_rejected(self):
        self.post(valid_payload())
        resp = self.post(valid_payload(username="newbie", email="other@163.com"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("用户名", str(resp.json()["error"]))

    def test_duplicate_username_case_insensitive_rejected(self):
        self.post(valid_payload())
        resp = self.post(valid_payload(username="Newbie", email="other@163.com"))
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_email_rejected(self):
        self.post(valid_payload(email="user@163.com"))
        resp = self.post(valid_payload(username="another", email="user@163.com"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("邮箱", str(resp.json()["error"]))

    def test_duplicate_email_case_insensitive_rejected(self):
        self.post(valid_payload(email="user@163.com"))
        resp = self.post(valid_payload(username="another", email="USER@163.COM"))
        self.assertEqual(resp.status_code, 400)

    def test_email_taken_by_pending_identifier_rejected(self):
        # A 正在验 user@163.com（pending identifier）；B 注册同邮箱应判重
        self.post(valid_payload(username="a", email="user@163.com"))
        resp = self.post(valid_payload(username="b", email="user@163.com"))
        self.assertEqual(resp.status_code, 400)

    def test_email_taken_by_verified_user_email_rejected(self):
        # 一个已验证用户 User.email 占了该地址 → 新注册判重
        u = User.objects.create_user(username="verified", password="p")
        u.email = "taken@163.com"
        u.save()
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_EMAIL, status=Verification.STATUS_APPROVED,
            identifier="taken@163.com",
        )
        resp = self.post(valid_payload(username="fresh", email="taken@163.com"))
        self.assertEqual(resp.status_code, 400)

    # ---- 字段校验 ----
    def test_invalid_identity_rejected(self):
        # identity 必填且须合法枚举（teacher 为合法身份，用非法值测）
        self.assertEqual(self.post(valid_payload(identity="alien")).status_code, 400)

    def test_invalid_email_format_rejected(self):
        self.assertEqual(self.post(valid_payload(email="not-an-email")).status_code, 400)

    def test_password_mismatch_rejected(self):
        self.assertEqual(self.post(valid_payload(password2="DifferentPass1!")).status_code, 400)

    def test_weak_password_rejected(self):
        resp = self.post(valid_payload(password="12345678", password2="12345678"))
        self.assertEqual(resp.status_code, 400)

    def test_empty_password_rejected(self):
        fields = valid_payload(password="", password2="")
        resp = self.post(fields)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(User.objects.filter(username="newbie").exists())

    # ---- 回归：不再强制邮箱 / 证明（真实姓名 / 身份为必填，见上）----
    def test_email_not_required(self):
        resp = self.post(valid_payload())  # 不带 email
        self.assertEqual(resp.status_code, 201)

    def test_proof_not_required(self):
        # 注册不再要证明；即使不带任何文件也成功
        resp = self.post(valid_payload())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(IdentityProof.objects.filter(user__username="newbie").count(), 0)

    # ---- 限流 ----
    def test_throttle_blocks_after_daily_limit(self):
        # register scope = 5/day；空 POST 也计次（allow_request 在校验之前）。
        for _ in range(5):
            self.assertEqual(self.client.post("/auth/register/", data={}).status_code, 400)
        resp = self.client.post("/auth/register/", data={})
        self.assertEqual(resp.status_code, 429)

    # ---- Turnstile 接线 ----
    @override_settings(TURNSTILE_SITE_KEY="", TURNSTILE_SECRET_KEY="")
    def test_turnstile_skipped_when_keys_empty(self):
        payload = valid_payload()
        payload.pop("turnstile_token")
        resp = self.post(payload)
        self.assertEqual(resp.status_code, 201, resp.content)

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="")
    def test_turnstile_skipped_when_only_sitekey(self):
        payload = valid_payload()
        payload.pop("turnstile_token")
        resp = self.post(payload)
        self.assertEqual(resp.status_code, 201, resp.content)

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="test-secret")
    def test_turnstile_empty_token_rejected_when_enabled(self):
        payload = valid_payload()
        payload["turnstile_token"] = ""
        resp = self.post(payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("人机校验", str(resp.json()["error"]))

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="test-secret")
    def test_turnstile_failure_rejected_when_configured(self):
        import accounts.views as views

        orig = views.passes_turnstile
        views.passes_turnstile = lambda request, token="": False
        try:
            resp = self.post(valid_payload())
            self.assertEqual(resp.status_code, 400)
            self.assertIn("人机校验", str(resp.json()["error"]))
        finally:
            views.passes_turnstile = orig


class IdentityProofStorageTest(TestCase):
    """证明材料落私有存储、不经公开 MEDIA_URL 暴露（IdentityProof 永久留底；注册不再上传）。

    经 ORM 直接造（#38 人工通道提交时由视图创建）。
    """

    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p", email="u@e.com")

    def test_proof_stored_under_private_media_not_public(self):
        proof_obj = IdentityProof.objects.create(user=self.user, file=proof())
        path = Path(proof_obj.file.path).resolve()
        private = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
        media = Path(settings.MEDIA_ROOT).resolve()
        self.assertTrue(path.is_relative_to(private))
        self.assertFalse(path.is_relative_to(media))

    def test_proof_not_served_via_public_media_url(self):
        IdentityProof.objects.create(user=self.user, file=proof("x.png"))
        url = settings.MEDIA_URL + "identity_proofs/x.png"
        resp = self.client.get(url)
        self.assertNotEqual(resp.status_code, 200)
