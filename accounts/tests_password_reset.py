"""注册三条件查重 + 忘记密码手动重置 + 首次登录强制改密（2026-10）。

覆盖：
- 注册查重：用户名 / 邮箱（含 pending 通道）/ 真实姓名任一命中即拒，提示登录原账户；
  已注销账号单独提示。
- 申请：匿名 multipart 提交（账号 + 身份证明），审批人收到站内通知；缺证明拒 400，
  账号状态（不存在 / 已注销 / 已停用 / 已有待处理）一律回同一 201（审计 #276），
  只有真实姓名重名保留 400。
- 审批：批准 = 密码 123456 + 强制改密标记 + 吊销会话；驳回不动密码；不能审批自己。
- 强制改密：登录响应带标记、中间件拦其他请求、改密成功后放行。
"""
import json

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from .models import (
    AccountLifecycle, MemberIdentity, PasswordResetRequest, Profile, UserSession, Verification,
)
from .testing import make_profile

#: 与 ``accounts/views.py: _RESET_REQUEST_ACK`` 逐字相同。测试里写死字面量
#: 而不是 import 常量：文案本身是契约的一部分（审计 #276 要求「同一段文案」），
#: 改文案就该让测试红一次。
_ACK = "若账号存在，申请已提交。管理员核对身份证明后会重置密码，请留意站内通知。"

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489000000"
    "0d49444154789c6360606060000000050001a5f645400000000049454e44ae426082"
)


def proof(name="proof.png", content_type="image/png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type=content_type)


def register_payload(**overrides):
    data = {
        "username": "newbie",
        "password": "StrongPass123!",
        "password2": "StrongPass123!",
        "real_name": "张三",
        "identity": "student",
        "turnstile_token": "dummy",
    }
    data.update(overrides)
    return data


class RegistrationDuplicateTest(TestCase):
    def setUp(self):
        cache.clear()
        self.existing = User.objects.create_user(
            username="olduser", email="old@163.com", password="StrongPass123!",
        )
        make_profile(
            user=self.existing, real_name="李四", identity="student", card_no="A-1024",
        )

    def post(self, **overrides):
        return self.client.post("/auth/register/", data=register_payload(**overrides))

    def test_duplicate_username_rejected_with_login_hint(self):
        resp = self.post(username="OldUser")
        self.assertEqual(resp.status_code, 409, resp.content)
        body = resp.json()
        self.assertEqual(body["reason"], "account_exists")
        self.assertEqual(body["field"], "username")
        self.assertIn("请登录原账户", body["error"])

    # 2026-10-24 调整：真实姓名不单独判重（校内同名同姓很常见），
    # 只有「姓名 + 校牌号」同时一致才视为同一账户。
    def test_same_real_name_without_card_allowed(self):
        resp = self.post(username="another", real_name="李四")
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_same_real_name_and_card_rejected(self):
        resp = self.post(username="another2", real_name="李四", card_no=" a-1024 ")
        self.assertEqual(resp.status_code, 409, resp.content)
        body = resp.json()
        self.assertEqual(body["field"], "real_name_card_no")
        self.assertIn("请登录原账户", body["error"])

    def test_same_name_and_card_normalized(self):
        # 全角空格 / 连续空白 / 首尾空白归一后仍判重；校牌号去空白、大小写不敏感
        resp = self.post(username="another3", real_name="  李　四 ", card_no="a-1024")
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.json()["field"], "real_name_card_no")

    def test_same_name_different_card_allowed(self):
        resp = self.post(username="another4", real_name="李四", card_no="A-9999")
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_same_card_different_name_allowed(self):
        resp = self.post(username="another5", real_name="王五", card_no="A-1024")
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_same_name_and_roster_card_rejected_when_profile_blank(self):
        # 历史账号只绑了名册、Profile.card_no 还没回写：仍要拦住
        self.existing.identity_record.pending_card_no = ""
        self.existing.identity_record.save(update_fields=["pending_card_no"])
        MemberIdentity.objects.create(
            name="李四", card_no="B-2000", admit_year=2025, cohort=1,
            code="25010101", user=self.existing, bind_method=MemberIdentity.BIND_ADMIN,
        )
        resp = self.post(username="another6", real_name="李四", card_no="b-2000")
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.json()["field"], "real_name_card_no")

    def test_duplicate_bound_email_rejected(self):
        resp = self.post(username="another3", real_name="王五", email="OLD@163.com")
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.json()["field"], "email")

    def test_duplicate_pending_email_rejected(self):
        pending = User.objects.create_user(username="pendinguser", password="StrongPass123!")
        make_profile(user=pending, real_name="赵六", identity="student")
        Verification.objects.create(
            user=pending, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING, identifier="pending@qq.com",
        )
        resp = self.post(username="another4", real_name="钱七", email="pending@qq.com")
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.json()["field"], "email")

    def test_deleted_account_gets_distinct_message(self):
        self.existing.lifecycle.deleted_at = timezone.now()
        self.existing.lifecycle.save(update_fields=["deleted_at"])
        resp = self.post(username="olduser")
        self.assertEqual(resp.status_code, 409, resp.content)
        body = resp.json()
        self.assertEqual(body["reason"], "account_deleted")
        self.assertIn("已注销", body["error"])

    def test_distinct_identity_can_register(self):
        resp = self.post(username="fresh", real_name="孙八", email="fresh@163.com")
        self.assertEqual(resp.status_code, 201, resp.content)


class PasswordResetRequestTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="member", email="member@163.com", password="OldPass123!",
        )
        make_profile(user=self.user, real_name="周九", identity="student")
        self.reviewer = User.objects.create_user(username="boss", password="BossPass123!")
        perm = Permission.objects.get(
            content_type__app_label="accounts", codename="review_password_reset",
        )
        self.reviewer.user_permissions.add(perm)

    def submit(self, **overrides):
        data = {
            "account": "member",
            "contact": "13800000000",
            "note": "换了手机，邮箱也忘了",
            "proof": proof(),
            "turnstile_token": "dummy",
        }
        data.update(overrides)
        return self.client.post("/auth/password-reset/request/", data=data)

    def test_submit_creates_request_and_notifies_reviewer(self):
        resp = self.submit()
        self.assertEqual(resp.status_code, 201, resp.content)
        request_obj = PasswordResetRequest.objects.get(user=self.user)
        self.assertEqual(request_obj.status, PasswordResetRequest.STATUS_PENDING)
        self.assertTrue(request_obj.proof.name.startswith("password_reset_proofs/"))
        self.assertTrue(
            self.reviewer.notifications.filter(event="password_reset_requested").exists()
        )

    def test_submit_accepts_email_identifier(self):
        resp = self.submit(account="member@163.com")
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_submit_accepts_unique_real_name(self):
        resp = self.submit(account="周九")
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_submit_unknown_account(self):
        """审计 #276：账号不存在不能与成功区分（原 404 → 现 201 同一文案）。"""
        resp = self.submit(account="nobody")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json(), {"message": _ACK})
        self.assertFalse(PasswordResetRequest.objects.exists())

    def test_submit_ambiguous_real_name(self):
        """姓名重名：保留 400（名册本就公开，且不提示用户无法自救）。"""
        other = User.objects.create_user(username="other", password="StrongPass123!")
        make_profile(user=other, real_name="周九", identity="student")
        resp = self.submit(account="周九")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["reason"], "account_ambiguous")

    def test_submit_requires_proof(self):
        resp = self.submit(proof="")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("身份证明", resp.json()["error"])

    def test_submit_rejects_wrong_file_type(self):
        """类型判定看**真实内容**：不是图片的文件即使声称 image/png 也要拒。"""
        fake = SimpleUploadedFile("proof.png", b"<html><script>alert(1)</script></html>", content_type="image/png")
        resp = self.submit(proof=fake)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("身份证明仅支持 JPG / PNG / WebP 格式", resp.json()["error"])

    def test_submit_rejects_duplicate_pending(self):
        """已有待处理申请：仍回 201 同一文案，且不重复建单。"""
        self.assertEqual(self.submit().status_code, 201)
        cache.clear()  # 绕开 5/日 的 IP 配额，测的是「重复提交」而不是限流
        resp = self.submit()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json(), {"message": _ACK})
        self.assertEqual(PasswordResetRequest.objects.count(), 1)

    def test_submit_rejects_deleted_account(self):
        """已注销：不再返回 account_deleted（那等于确认账号存在过）。"""
        self.user.lifecycle.deleted_at = timezone.now()
        self.user.lifecycle.save(update_fields=["deleted_at"])
        resp = self.submit()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json(), {"message": _ACK})
        self.assertFalse(PasswordResetRequest.objects.exists())

    def test_submit_rejects_disabled_account(self):
        """已停用：同上，不通过响应透露账号状态。"""
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        resp = self.submit()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json(), {"message": _ACK})
        self.assertFalse(PasswordResetRequest.objects.exists())

    def test_all_account_states_return_identical_response(self):
        """审计 #276 的核心断言：五种状态的状态码与响应体逐字相同。

        反证：把任一分支改回专属文案 / 专属状态码，本条立刻变红。
        每次请求前清缓存——5/日 的 IP 配额会让第 6 次变 429，掩盖真正的差异。
        """
        bodies = []

        def snapshot(label):
            cache.clear()
            resp = self.submit()
            bodies.append((label, resp.status_code, resp.json()))

        # 1) 待处理：先提交一次，再重复提交
        self.assertEqual(self.submit().status_code, 201)
        snapshot("pending")
        PasswordResetRequest.objects.all().delete()

        # 2) 不存在
        cache.clear()
        bodies.append(("missing", *self._status_body(self.submit(account="ghost"))))

        # 3) 正常受理
        cache.clear()
        bodies.append(("ok", *self._status_body(self.submit())))

        # 4) 已注销
        self.user.lifecycle.deleted_at = timezone.now()
        self.user.lifecycle.save(update_fields=["deleted_at"])
        cache.clear()
        bodies.append(("deleted", *self._status_body(self.submit())))

        # 5) 已停用
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        cache.clear()
        bodies.append(("disabled", *self._status_body(self.submit())))

        reference = {b[1] for b in bodies}
        self.assertEqual(reference, {201}, f"状态码不一致：{bodies}")
        messages = {json.dumps(b[2], sort_keys=True, ensure_ascii=False) for b in bodies}
        self.assertEqual(len(messages), 1, f"响应体不一致：{bodies}")

    @staticmethod
    def _status_body(resp):
        return resp.status_code, resp.json()

    def test_list_requires_permission(self):
        self.client.force_login(self.user)
        resp = self.client.get("/auth/password-reset-requests/")
        self.assertEqual(resp.status_code, 403)

    def test_list_and_proof_for_reviewer(self):
        self.submit()
        request_obj = PasswordResetRequest.objects.get(user=self.user)
        self.client.force_login(self.reviewer)
        listing = self.client.get("/auth/password-reset-requests/?status=pending")
        self.assertEqual(listing.status_code, 200, listing.content)
        self.assertEqual(listing.json()["count"], 1)
        row = listing.json()["results"][0]
        self.assertEqual(row["username"], "member")
        self.assertIn("/proof/", row["proof_url"])

        file_resp = self.client.get(row["proof_url"])
        self.assertEqual(file_resp.status_code, 200)
        self.assertEqual(file_resp["Content-Type"], "image/png")

    def test_proof_forbidden_for_other_user(self):
        self.submit()
        request_obj = PasswordResetRequest.objects.get(user=self.user)
        intruder = User.objects.create_user(username="intruder", password="StrongPass123!")
        self.client.force_login(intruder)
        resp = self.client.get(f"/auth/password-reset-requests/{request_obj.pk}/proof/")
        self.assertEqual(resp.status_code, 403)

    def test_approve_resets_password_and_requires_change(self):
        self.submit()
        request_obj = PasswordResetRequest.objects.get(user=self.user)
        # 造一个既有会话，验证批准后会被吊销
        UserSession.objects.create(user=self.user, session_key="old-session")
        self.client.force_login(self.reviewer)
        resp = self.client.post(
            f"/auth/password-reset-requests/{request_obj.pk}/approve/",
            data={"note": "学生证核对无误"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        request_obj.refresh_from_db()
        self.user.refresh_from_db()
        self.user.lifecycle.refresh_from_db()
        self.assertEqual(request_obj.status, PasswordResetRequest.STATUS_APPROVED)
        self.assertEqual(request_obj.moderated_by, self.reviewer)
        self.assertEqual(request_obj.moderation_note, "学生证核对无误")
        self.assertIsNotNone(request_obj.reset_at)
        temp = resp.json()["temp_password"]
        self.assertNotEqual(temp, "123456")
        self.assertTrue(self.user.check_password(temp))
        self.assertTrue(self.user.lifecycle.must_change_password)
        self.assertFalse(
            UserSession.objects.filter(user=self.user, revoked_at__isnull=True).exists()
        )

    def test_cannot_approve_own_request(self):
        request_obj = PasswordResetRequest.objects.create(
            user=self.reviewer, identifier="boss", proof=proof(),
        )
        self.client.force_login(self.reviewer)
        resp = self.client.post(
            f"/auth/password-reset-requests/{request_obj.pk}/approve/",
            data={}, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.json()["reason"], "cannot_review_self")

    def test_reject_does_not_touch_password(self):
        self.submit()
        request_obj = PasswordResetRequest.objects.get(user=self.user)
        self.client.force_login(self.reviewer)
        resp = self.client.post(
            f"/auth/password-reset-requests/{request_obj.pk}/reject/",
            data={"note": "证明看不清"}, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        request_obj.refresh_from_db()
        self.user.refresh_from_db()
        self.user.lifecycle.refresh_from_db()
        self.assertEqual(request_obj.status, PasswordResetRequest.STATUS_REJECTED)
        self.assertTrue(self.user.check_password("OldPass123!"))
        self.assertFalse(self.user.lifecycle.must_change_password)

    def test_double_review_conflicts(self):
        self.submit()
        request_obj = PasswordResetRequest.objects.get(user=self.user)
        self.client.force_login(self.reviewer)
        self.client.post(
            f"/auth/password-reset-requests/{request_obj.pk}/approve/",
            data={}, content_type="application/json",
        )
        resp = self.client.post(
            f"/auth/password-reset-requests/{request_obj.pk}/approve/",
            data={}, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.json()["reason"], "already_reviewed")


class ForcedPasswordChangeTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="resetme", email="resetme@163.com", password="123456",
        )
        self.profile = make_profile(
            user=self.user, real_name="吴十", identity="student", must_change_password=True,
        )

    def test_login_response_flags_must_change(self):
        resp = self.client.post(
            "/auth/login/",
            data={"username": "resetme", "password": "123456"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["must_change_password"])

    def test_me_exposes_flag_and_other_endpoints_blocked(self):
        self.client.force_login(self.user)
        me = self.client.get("/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.json()["must_change_password"])

        blocked = self.client.get("/auth/verification/")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["reason"], "password_change_required")

    def test_force_change_success_clears_flag(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/auth/password/force-change/",
            data={"new_password": "BrandNewPass123!", "new_password2": "BrandNewPass123!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.user.refresh_from_db()
        self.user.lifecycle.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNewPass123!"))
        self.assertFalse(self.user.lifecycle.must_change_password)

        # 放行普通接口（verification 需要登录，200/内部状态即可）
        allowed = self.client.get("/auth/verification/")
        self.assertEqual(allowed.status_code, 200, allowed.content)

    def test_force_change_rejects_default_and_mismatch(self):
        self.client.force_login(self.user)
        same = self.client.post(
            "/auth/password/force-change/",
            data={"new_password": "123456", "new_password2": "123456"},
            content_type="application/json",
        )
        self.assertEqual(same.status_code, 400, same.content)

        mismatch = self.client.post(
            "/auth/password/force-change/",
            data={"new_password": "BrandNewPass123!", "new_password2": "OtherPass123!"},
            content_type="application/json",
        )
        self.assertEqual(mismatch.status_code, 400, mismatch.content)

    def test_force_change_not_required_for_normal_account(self):
        self.user.lifecycle.must_change_password = False
        self.user.lifecycle.save(update_fields=["must_change_password"])
        self.client.force_login(self.user)
        resp = self.client.post(
            "/auth/password/force-change/",
            data={"new_password": "BrandNewPass123!", "new_password2": "BrandNewPass123!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["reason"], "not_required")


class PasswordResetPrivilegeTests(TestCase):
    """S-2 回归：审批人不得重置权限高于自己的账号；不再使用固定默认密码。

    反证：
    - 去掉 ``password_reset.py`` 里的 ``_ensure_can_target()`` 调用 → 前两条变红（200）；
    - 把 ``generate_temp_password()`` 换回 ``"123456"`` → 临时密码那条变红。
    """

    def setUp(self):
        cache.clear()
        self.reviewer = User.objects.create_user(username="rev_x", password="Passw0rd!2026")
        perm = Permission.objects.get(
            content_type__app_label="accounts", codename="review_password_reset",
        )
        self.reviewer.user_permissions.add(perm)
        self.root = User.objects.create_superuser(
            username="root_x", email="root@example.com", password="RootPass!2026",
        )

    def _pending_for(self, user):
        return PasswordResetRequest.objects.create(user=user, identifier=user.username)

    def _approve(self, req, reviewer=None):
        self.client.force_login(reviewer or self.reviewer)
        return self.client.post(
            f"/auth/password-reset-requests/{req.pk}/approve/",
            data={}, content_type="application/json",
        )

    def test_cannot_reset_superuser(self):
        """持 review_password_reset 的普通管理员不能重置超管（纵向提权闸门）。"""
        req = self._pending_for(self.root)
        resp = self._approve(req)
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.json()["reason"], "target_outranks_reviewer")
        self.root.refresh_from_db()
        self.assertTrue(self.root.check_password("RootPass!2026"))

    def test_cannot_reset_staff_when_not_staff(self):
        staff = User.objects.create_user(username="staff_x", password="StaffPass!2026")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        resp = self._approve(self._pending_for(staff))
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.json()["reason"], "target_outranks_reviewer")

    def test_superuser_can_reset_superuser(self):
        """同级不限：超管重置超管仍允许。"""
        victim = User.objects.create_superuser(
            username="root_y", email="y@example.com", password="RootPass!2026",
        )
        boss = User.objects.create_superuser(
            username="root_z", email="z@example.com", password="RootPass!2026",
        )
        resp = self._approve(self._pending_for(victim), reviewer=boss)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json().get("temp_password"))

    def test_temp_password_is_random_and_can_log_in(self):
        """不再有固定 123456：重置后只能靠响应里那串一次性密码登录。"""
        member = User.objects.create_user(username="member_x", password="OldPass!2026")
        resp = self._approve(self._pending_for(member))
        self.assertEqual(resp.status_code, 200, resp.content)
        temp = resp.json()["temp_password"]
        self.assertNotEqual(temp, "123456")
        self.assertEqual(len(temp), 14)
        member.refresh_from_db()
        self.assertTrue(member.check_password(temp))
        self.assertFalse(member.check_password("123456"))
        self.assertTrue(AccountLifecycle.objects.get(user=member).must_change_password)

    def test_temp_password_is_not_reused(self):
        a = User.objects.create_user(username="m_a", password="OldPass!2026")
        b = User.objects.create_user(username="m_b", password="OldPass!2026")
        pa = self._approve(self._pending_for(a)).json()["temp_password"]
        pb = self._approve(self._pending_for(b)).json()["temp_password"]
        self.assertNotEqual(pa, pb)
