"""认证码通道（ADR-0020）：生成 / 归一化 / 兑换 / 校验 / 节流 / 后台生成侧。

覆盖：码形与状态派生、兑换全链路（成功 / 无效 / 过期 / 用尽 / 吊销 / 归一化 /
多用户共用）、已通过不消耗码、站点开关、按账号只计失败节流、后台 add 权限、
只读规则、吊销动作、删除规则、0012 授权迁移。
"""
import json
from datetime import timedelta

from django.contrib import admin
from django.contrib.auth.models import Group, Permission, User
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone


from accounts.admin import AuthCodeAdmin, AuthCodeRedemptionAdmin, revoke_authcodes
from accounts.authcode import (
    AuthCodeError,
    generate_authcode_value,
    normalize_authcode,
    redeem_authcode,
)
from accounts.models import AuthCode, AuthCodeRedemption, Verification, is_verified
from common.testing import set_policy

REDEEM_URL = "/auth/verification/authcode/redeem/"
STATUS_URL = "/auth/verification/"




def make_code(code="TEST2345ABCD", *, expires_in=timedelta(days=1), max_uses=1, revoked=False, created_by=None):
    return AuthCode.objects.create(
        code=code,
        expires_at=timezone.now() + expires_in,
        max_uses=max_uses,
        revoked_at=timezone.now() if revoked else None,
        created_by=created_by,
    )


class AuthCodeValueTest(TestCase):
    """码形与归一化（纯函数）。"""

    def test_generated_value_shape(self):
        value = generate_authcode_value()
        self.assertEqual(len(value), 12)
        self.assertTrue(set(value) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789"))  # 无 I/L/O/0/1
        self.assertNotEqual(value, generate_authcode_value())

    def test_normalize_strips_separators_and_uppercases(self):
        self.assertEqual(normalize_authcode(" nh7k-2m9q x4tp "), "NH7K2M9QX4TP")
        self.assertEqual(normalize_authcode(""), "")
        self.assertEqual(normalize_authcode(None), "")


class AuthCodeStatusPropertyTest(TestCase):
    """派生状态优先级：吊销 > 过期 > 用尽 > 有效。"""

    def test_valid(self):
        self.assertEqual(make_code().status, "valid")

    def test_expired(self):
        self.assertEqual(make_code(expires_in=timedelta(days=-1)).status, "expired")

    def test_exhausted(self):
        code = make_code(max_uses=1)
        code.used_count = 1
        self.assertEqual(code.status, "exhausted")

    def test_revoked(self):
        self.assertEqual(make_code(revoked=True).status, "revoked")

    def test_priority_revoked_over_expired(self):
        code = make_code(expires_in=timedelta(days=-1), revoked=True)
        self.assertEqual(code.status, "revoked")

    def test_priority_expired_over_exhausted(self):
        code = make_code(expires_in=timedelta(days=-1), max_uses=1)
        code.used_count = 1
        self.assertEqual(code.status, "expired")


class RedeemViewTest(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(username="u", password="StrongPass123!")

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def post(self, payload, user=None):
        c = Client()
        c.force_login(user or self.user)
        return c.post(REDEEM_URL, data=json.dumps(payload), content_type="application/json")

    def test_requires_login(self):
        resp = Client().post(REDEEM_URL, data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 302)

    def test_get_not_allowed(self):
        c = Client()
        c.force_login(self.user)
        self.assertEqual(c.get(REDEEM_URL).status_code, 405)

    def test_invalid_json(self):
        c = Client()
        c.force_login(self.user)
        resp = c.post(REDEEM_URL, data="{not json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_empty_code(self):
        resp = self.post({"code": "   "})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("请输入", resp.json()["error"])

    def test_redeem_success_full_chain(self):
        maker = User.objects.create_user(username="maker", password="p")
        code = make_code("AAAAAAAAAAAA", created_by=maker)
        resp = self.post({"code": "AAAAAAAAAAAA"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("完成认证", resp.json()["message"])

        self.assertTrue(is_verified(self.user))
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_AUTHCODE)
        self.assertEqual(v.status, Verification.STATUS_APPROVED)
        self.assertEqual(v.identifier, "AAAAAAAAAAAA")  # 码原文入库（后台可读）
        self.assertEqual(v.verified_by, maker)  # 发码人留痕
        self.assertIsNotNone(v.verified_at)

        code.refresh_from_db()
        self.assertEqual(code.used_count, 1)
        self.assertEqual(AuthCodeRedemption.objects.get(user=self.user).authcode, code)

    def test_redeem_normalized_input(self):
        make_code("NH7K2M9QX4TP")
        resp = self.post({"code": " nh7k-2m9q-x4tp "})
        self.assertEqual(resp.status_code, 200)

    def test_unknown_code(self):
        resp = self.post({"code": "NOSUCHCODE22"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("无效", resp.json()["error"])
        self.assertFalse(is_verified(self.user))

    def test_expired_code(self):
        make_code("EXPIRED00000", expires_in=timedelta(days=-1))
        resp = self.post({"code": "EXPIRED00000"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("已过期", resp.json()["error"])

    def test_revoked_code(self):
        make_code("REVOKED00000", revoked=True)
        resp = self.post({"code": "REVOKED00000"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("吊销", resp.json()["error"])

    def test_exhausted_code(self):
        make_code("EXHAUSTED000", max_uses=1)
        other = User.objects.create_user(username="other", password="p")
        self.assertEqual(self.post({"code": "EXHAUSTED000"}, user=other).status_code, 200)
        resp = self.post({"code": "EXHAUSTED000"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("已用尽", resp.json()["error"])

    def test_multi_use_code_serves_two_users(self):
        make_code("MULTIUSE0000", max_uses=2)
        u2 = User.objects.create_user(username="u2", password="p")
        self.assertEqual(self.post({"code": "MULTIUSE0000"}).status_code, 200)
        self.assertEqual(self.post({"code": "MULTIUSE0000"}, user=u2).status_code, 200)
        u3 = User.objects.create_user(username="u3", password="p")
        resp = self.post({"code": "MULTIUSE0000"}, user=u3)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("已用尽", resp.json()["error"])

    def test_already_verified_user_does_not_consume_code(self):
        # 已通过（邮箱通道）用户兑换 → 400，且不消耗码、不落记录（不回溯的对偶：不多扣）
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_APPROVED,
        )
        code = make_code("KEEPME123456")
        resp = self.post({"code": "KEEPME123456"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("已完成认证", resp.json()["error"])
        code.refresh_from_db()
        self.assertEqual(code.used_count, 0)
        self.assertFalse(AuthCodeRedemption.objects.filter(user=self.user).exists())

    def test_verification_closed_blocks_redeem(self):
        set_policy(verification_enabled=False)
        make_code("CLOSED000000")
        resp = self.post({"code": "CLOSED000000"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "verification_closed")

    def test_status_endpoint_shows_authcode_card(self):
        make_code("SHOWCASE0000")
        self.post({"code": "SHOWCASE0000"})
        c = Client()
        c.force_login(self.user)
        data = c.get(STATUS_URL).json()
        self.assertTrue(data["is_verified"])
        card = {ch["channel"]: ch for ch in data["channels"]}["authcode"]
        self.assertEqual(card["status"], "approved")
        self.assertEqual(card["identifier"], "SHOWCASE0000")


class RedeemThrottleTest(TestCase):
    """按账号节流：只计失败；成功不占额度；达限后连正确码也被拒。"""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(username="u", password="p")

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def post(self, payload, user=None):
        c = Client()
        c.force_login(user or self.user)
        return c.post(REDEEM_URL, data=json.dumps(payload), content_type="application/json")

    def test_failures_block_after_limit_even_with_valid_code(self):
        set_policy(authcode_redeem_per_user_per_hour=2)
        make_code("VALID0000000")
        for _ in range(2):
            self.assertEqual(self.post({"code": "NOSUCHCODE000"}).status_code, 400)
        resp = self.post({"code": "VALID0000000"})
        self.assertEqual(resp.status_code, 429)

    def test_success_is_not_counted(self):
        set_policy(authcode_redeem_per_user_per_hour=2)
        self.assertEqual(self.post({"code": "NOSUCHCODE000"}).status_code, 400)  # 计 1 次
        make_code("GOOD00000000")
        self.assertEqual(self.post({"code": "GOOD00000000"}).status_code, 200)  # 成功不计数
        # 若成功被计数（rec=2=limit）这里应是 429；实际应停在「已通过」400
        resp = self.post({"code": "WHATEVER0000"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("已完成认证", resp.json()["error"])

    def test_empty_code_is_not_counted(self):
        set_policy(authcode_redeem_per_user_per_hour=1)
        self.assertEqual(self.post({"code": ""}).status_code, 400)  # 不计
        self.assertEqual(self.post({"code": "NOSUCHCODE000"}).status_code, 400)  # 计 1
        self.assertEqual(self.post({"code": "NOSUCHCODE000"}).status_code, 429)  # 达限

    def test_throttle_is_per_account(self):
        set_policy(authcode_redeem_per_user_per_hour=1)
        other = User.objects.create_user(username="other", password="p")
        self.assertEqual(self.post({"code": "NOSUCHCODE000"}).status_code, 400)
        self.assertEqual(self.post({"code": "NOSUCHCODE000"}).status_code, 429)
        make_code("OTHER0000000")
        self.assertEqual(self.post({"code": "OTHER0000000"}, user=other).status_code, 200)


class RedeemServiceTest(TestCase):
    def test_second_redemption_by_same_user_rejected(self):
        user = User.objects.create_user(username="u", password="p")
        make_code("FIRST0000000")
        redeem_authcode(user, "FIRST0000000")
        make_code("SECOND000000")
        with self.assertRaises(AuthCodeError):
            redeem_authcode(user, "SECOND000000")


class AuthCodeAdminTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser("adm", "adm@example.com", "p")
        self.ma = AuthCodeAdmin(AuthCode, admin.site)
        self.ma.message_user = lambda *a, **k: None

    def _req(self, user):
        req = self.factory.post("/")
        req.user = user
        return req

    def test_changeform_initial_prefills_code(self):
        data = self.ma.get_changeform_initial_data(self._req(self.admin))
        self.assertEqual(len(data["code"]), 12)
        self.assertEqual(data["max_uses"], 1)
        self.assertIn("expires_at", data)

    def test_readonly_fields(self):
        req = self._req(self.admin)
        self.assertNotIn("max_uses", self.ma.get_readonly_fields(req, obj=None))  # 新增可改
        ro = self.ma.get_readonly_fields(req, obj=make_code())
        for field in ("code", "max_uses", "created_by", "used_count", "revoked_at"):
            self.assertIn(field, ro)  # 生成后码 / 次数 / 生成人不可改

    def test_save_model_sets_created_by(self):
        obj = AuthCode(code="SAVED0000000", expires_at=timezone.now() + timedelta(days=1))
        self.ma.save_model(self._req(self.admin), obj, form=None, change=False)
        obj.refresh_from_db()
        self.assertEqual(obj.created_by, self.admin)

    def test_delete_permission_rules(self):
        req = self._req(self.admin)
        self.assertTrue(self.ma.has_delete_permission(req, make_code("FRESH0000000")))
        used = make_code("USED00000000")
        used.used_count = 1
        self.assertFalse(self.ma.has_delete_permission(req, used))
        self.assertFalse(self.ma.has_delete_permission(req, make_code("REVOKED00000", revoked=True)))

    def test_revoke_action_marks_and_skips(self):
        a = make_code("AAA000000000")
        b = make_code("BBB000000000", revoked=True)
        old = b.revoked_at
        revoke_authcodes(self.ma, self._req(self.admin), AuthCode.objects.all())
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertIsNotNone(a.revoked_at)
        self.assertEqual(b.revoked_at, old)  # 已吊销的跳过

    def test_revoke_action_requires_perm(self):
        staff = User.objects.create_user(username="staff", password="p")
        a = make_code("CCC000000000")
        revoke_authcodes(self.ma, self._req(staff), AuthCode.objects.all())
        a.refresh_from_db()
        self.assertIsNone(a.revoked_at)

    def test_add_page_requires_perm(self):
        staff = User.objects.create_user(username="staff", password="p", is_staff=True)
        c = Client()
        c.force_login(staff)
        self.assertEqual(c.get("/admin/accounts/authcode/add/").status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename="add_authcode"))
        c2 = Client()
        c2.force_login(User.objects.get(pk=staff.pk))
        self.assertEqual(c2.get("/admin/accounts/authcode/add/").status_code, 200)

    def test_changelist_visible_with_view_perm(self):
        staff = User.objects.create_user(username="staff", password="p", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_authcode"))
        c = Client()
        c.force_login(User.objects.get(pk=staff.pk))
        self.assertEqual(c.get("/admin/accounts/authcode/").status_code, 200)

    def test_redemption_admin_readonly(self):
        ra = AuthCodeRedemptionAdmin(AuthCodeRedemption, admin.site)
        req = self._req(self.admin)
        self.assertFalse(ra.has_add_permission(req))
        self.assertFalse(ra.has_change_permission(req, None))
        self.assertFalse(ra.has_delete_permission(req, None))
        viewer = User.objects.create_user(username="viewer", password="p")
        self.assertFalse(ra.has_view_permission(self._req(viewer)))
        viewer.user_permissions.add(Permission.objects.get(codename="view_authcode"))
        viewer = User.objects.get(pk=viewer.pk)  # 刷新权限缓存
        self.assertTrue(ra.has_view_permission(self._req(viewer)))


class GrantMigrationTest(TestCase):
    def test_editor_groups_received_authcode_crud(self):
        wanted = {"add_authcode", "view_authcode", "change_authcode", "delete_authcode"}
        for name in ("社长", "信息组"):
            group = Group.objects.get(name=name)
            got = set(
                group.permissions.filter(content_type__app_label="accounts")
                .values_list("codename", flat=True)
            )
            self.assertTrue(wanted <= got, f"{name} 缺少 {wanted - got}")
