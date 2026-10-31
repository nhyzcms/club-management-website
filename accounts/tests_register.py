"""注册（ADR-0006 注册↔认证分离，2026-09 修订）：建登录身份（用户名 + 密码 + Turnstile）
+ 真实姓名 / 身份（必填，写入 Profile），邮箱可选。

覆盖：最小注册建 User+Profile（无 Verification 行 ⇒ 访客）；带邮箱注册建 email 通道 pending
并发认证信（User.email 保持空）；必填 real_name/identity；用户名/邮箱唯一；密码校验；
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

from accounts.models import IdentityProof, MemberIdentity, Verification, is_verified

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
        self.assertEqual(user.email, "")  # 无邮箱 → User.email 空（只装已认证邮箱）
        self.assertTrue(user.is_active)
        # 新号无 Verification 行 ⇒ 未认证（访客）
        self.assertEqual(Verification.objects.filter(user=user).count(), 0)
        self.assertFalse(is_verified(user))
        # 无邮箱不发信
        self.assertEqual(len(mail.outbox), 0)

    def test_register_creates_profile_without_legacy_verification_fields(self):
        self.post(valid_payload())
        user = User.objects.get(username="newbie")
        # Profile 存在；认证态不在 Profile 上（已删四字段）
        self.assertTrue(user.profile)
        for gone in ("email_verified", "identity_verified", "verified_at", "verified_by"):
            self.assertFalse(hasattr(user.profile, gone))

    # ---- 带邮箱注册：建 email 通道 pending + 发信，User.email 不动 ----
    def test_register_with_email_starts_email_verification(self):
        resp = self.post(valid_payload(email="newbie@163.com"))
        self.assertEqual(resp.status_code, 201, resp.content)

        user = User.objects.get(username="newbie")
        self.assertEqual(user.email, "")  # 待认证邮箱不住 User.email
        v = Verification.objects.get(user=user, channel=Verification.CHANNEL_EMAIL)
        self.assertEqual(v.status, Verification.STATUS_PENDING)
        self.assertEqual(v.identifier, "newbie@163.com")
        # 仅 email 通道 pending（未 approved）⇒ 仍未认证
        self.assertFalse(is_verified(user))
        # 认证信发往待认证地址
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
    # 2026-10 起重复注册统一 409 + reason=account_exists（提示登录原账户），
    # 不再是 400 的普通字段错误。
    def test_duplicate_username_rejected(self):
        self.post(valid_payload())
        resp = self.post(valid_payload(
            username="newbie", real_name="李四", email="other@163.com",
        ))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["reason"], "account_exists")
        self.assertEqual(resp.json()["field"], "username")
        self.assertIn("用户名", str(resp.json()["error"]))
        self.assertIn("请登录原账户", str(resp.json()["error"]))

    def test_duplicate_username_case_insensitive_rejected(self):
        self.post(valid_payload())
        resp = self.post(valid_payload(
            username="Newbie", real_name="李四", email="other@163.com",
        ))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["field"], "username")

    def test_duplicate_email_rejected(self):
        self.post(valid_payload(email="user@163.com"))
        resp = self.post(valid_payload(
            username="another", real_name="李四", email="user@163.com",
        ))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["field"], "email")
        self.assertIn("邮箱", str(resp.json()["error"]))

    def test_duplicate_email_case_insensitive_rejected(self):
        self.post(valid_payload(email="user@163.com"))
        resp = self.post(valid_payload(
            username="another", real_name="李四", email="USER@163.COM",
        ))
        self.assertEqual(resp.status_code, 409)

    def test_email_taken_by_pending_identifier_rejected(self):
        # A 正在验 user@163.com（pending identifier）；B 注册同邮箱应判重
        self.post(valid_payload(username="a", real_name="甲", email="user@163.com"))
        resp = self.post(valid_payload(username="b", real_name="乙", email="user@163.com"))
        self.assertEqual(resp.status_code, 409)

    def test_email_taken_by_verified_user_email_rejected(self):
        # 一个已认证用户 User.email 占了该地址 → 新注册判重
        u = User.objects.create_user(username="verified", password="p")
        u.email = "taken@163.com"
        u.save()
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_EMAIL, status=Verification.STATUS_APPROVED,
            identifier="taken@163.com",
        )
        resp = self.post(valid_payload(username="fresh", real_name="李四", email="taken@163.com"))
        self.assertEqual(resp.status_code, 409)

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


class RegisterCardNoTest(TestCase):
    """注册页「校牌号」（ADR-0025 2026-10-23 增补）：在校生 / 毕业生选填，与名册同一字段。"""

    def setUp(self):
        cache.clear()  # 注册限流按 IP 计数；隔离每个用例。

    def post(self, **overrides):
        return self.client.post("/auth/register/", data=valid_payload(**overrides))

    def make_row(self, name="张三", card_no="A001", phone="13800008888", code="26020001"):
        return MemberIdentity.objects.create(
            name=name, admit_year=2026, cohort=2, phone=phone,
            code=code, card_no=card_no,
        )

    def test_card_no_stored_for_student_and_graduate(self):
        for idx, identity in enumerate(("student", "graduate"), start=1):
            username = f"newbie{idx}"
            # 真实姓名也要不同：同名会被 2026-10 的三条件查重拦下（另见 tests_password_reset）
            resp = self.post(
                username=username, real_name=f"测试{idx}", identity=identity, card_no=" A-1024 ",
            )
            self.assertEqual(resp.status_code, 201, resp.content)
            self.assertEqual(User.objects.get(username=username).profile.card_no, "A-1024")

    def test_card_no_ignored_for_other_identities(self):
        self.post(identity="teacher", card_no="A001")
        self.assertEqual(User.objects.get(username="newbie").profile.card_no, "")

    def test_card_no_too_long_rejected(self):
        resp = self.post(card_no="X" * 21)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("校牌号", str(resp.json()["error"]))
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_auto_bind_when_name_and_card_match(self):
        row = self.make_row(card_no="A001")
        resp = self.post(card_no="A001")
        self.assertEqual(resp.status_code, 201, resp.content)
        row.refresh_from_db()
        user = User.objects.get(username="newbie")
        self.assertEqual(row.user_id, user.id)
        self.assertEqual(row.bind_method, MemberIdentity.BIND_REGISTER)
        # B4：绑定成功 → 暂存清空，权威在名册行
        self.assertEqual(user.profile.card_no, "")

    def test_no_bind_when_card_differs(self):
        row = self.make_row(card_no="A001")
        self.post(card_no="A002")
        row.refresh_from_db()
        self.assertIsNone(row.user_id)
        self.assertEqual(User.objects.get(username="newbie").profile.card_no, "A002")

    def test_no_bind_when_roster_card_blank(self):
        row = self.make_row(card_no="")
        self.post(card_no="A001")
        row.refresh_from_db()
        self.assertIsNone(row.user_id)  # 名册没有校牌号 → 不猜，留给认领
        self.assertEqual(User.objects.get(username="newbie").profile.card_no, "A001")

    def test_binds_matching_row_among_same_name(self):
        mine = self.make_row(card_no="A001", code="26020001")
        other = self.make_row(card_no="A002", phone="13900001111", code="26020002")
        self.post(card_no=" a001 ")  # 空白 / 大小写归一后比较
        mine.refresh_from_db()
        other.refresh_from_db()
        self.assertIsNotNone(mine.user_id)
        self.assertIsNone(other.user_id)

    def test_register_without_card_no_still_works(self):
        resp = self.post()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(User.objects.get(username="newbie").profile.card_no, "")


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
