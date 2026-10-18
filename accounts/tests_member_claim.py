"""自助认领 / 扫码校验 / 注册即登录（ADR-0025 的 API 层）。

覆盖：候选与绑定状态接口、认领（成功 / 错四位 / 姓名不符 / 重复 / 无电话 /
节流 / 开关关闭）、公开校验（签名 / 篡改 / 枚举 / 限流 / 字段最小化）、
注册成功后自动登录（会话 + logged_in 标记）。
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

from accounts.member_codes import make_signature
from accounts.member_roster import claim_candidates, claim_identity
from accounts.models import MemberIdentity, Profile, UserSession
from accounts.tests_register import valid_payload
from common.models import SiteSettings


def make_row(name="张三", cohort=2, phone="11451419198", code="26020001"):
    return MemberIdentity.objects.create(
        name=name, admit_year=2026, cohort=cohort, group="摄影", phone=phone, code=code,
    )


def make_user(username="u1", real_name="张三"):
    user = User.objects.create_user(username=username, password="StrongPass123!")
    Profile.objects.create(user=user, real_name=real_name)
    return user


class MemberIdentityApiTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_login(self.user)

    def test_status_lists_name_matched_unbound_candidates_only(self):
        mine = make_row(code="26020001")
        make_row(name="李四", phone="13900001111", code="26020002")
        other = make_row(code="26020003")
        other.user = make_user(username="u2", real_name="王五")
        other.save()
        resp = self.client.get("/auth/member/")
        data = resp.json()
        self.assertTrue(data["enabled"])
        self.assertIsNone(data["bound"])
        self.assertEqual([c["id"] for c in data["candidates"]], [mine.id])
        self.assertNotIn("phone", data["candidates"][0])

    def test_status_bound_payload(self):
        row = make_row()
        row.user = self.user
        row.bind_method = MemberIdentity.BIND_ADMIN
        row.save()
        resp = self.client.get("/auth/member/")
        data = resp.json()
        self.assertEqual(data["bound"]["code"], "26020001")
        self.assertEqual(data["bound"]["cohort"], 2)
        self.assertEqual(data["candidates"], [])

    def test_claim_success(self):
        row = make_row()
        resp = self.client.post(
            "/auth/member/claim/",
            data={"identity_id": row.id, "phone_last4": "9198"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        row.refresh_from_db()
        self.assertEqual(row.user_id, self.user.id)
        self.assertEqual(row.bind_method, MemberIdentity.BIND_SELF)
        self.assertIsNotNone(row.bound_at)

    def test_claim_wrong_last4_and_throttle(self):
        row = make_row()
        for _ in range(5):
            resp = self.client.post(
                "/auth/member/claim/",
                data={"identity_id": row.id, "phone_last4": "0000"},
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 400)
        resp = self.client.post(
            "/auth/member/claim/",
            data={"identity_id": row.id, "phone_last4": "9198"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 429)  # 5 次失败后节流
        row.refresh_from_db()
        self.assertIsNone(row.user_id)

    def test_claim_name_mismatch_rejected(self):
        row = make_row(name="李四", phone="13900001111")
        resp = self.client.post(
            "/auth/member/claim/",
            data={"identity_id": row.id, "phone_last4": "1111"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不匹配", resp.json()["error"])

    def test_claim_row_already_bound(self):
        row = make_row()
        row.user = make_user(username="u9", real_name="李四")
        row.save()
        resp = self.client.post(
            "/auth/member/claim/",
            data={"identity_id": row.id, "phone_last4": "9198"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_claim_user_already_bound(self):
        mine = make_row(code="26020001")
        mine.user = self.user
        mine.save()
        other = make_row(name="张三", phone="13900001111", code="26020002")
        resp = self.client.post(
            "/auth/member/claim/",
            data={"identity_id": other.id, "phone_last4": "1111"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_claim_row_without_phone_rejected(self):
        row = make_row(phone="")
        resp = self.client.post(
            "/auth/member/claim/",
            data={"identity_id": row.id, "phone_last4": "9198"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_claim_disabled_by_policy(self):
        SiteSettings(pk=1, member_claim_enabled=False).save()
        row = make_row()
        resp = self.client.post(
            "/auth/member/claim/",
            data={"identity_id": row.id, "phone_last4": "9198"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "claim_closed")
        status = self.client.get("/auth/member/").json()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["candidates"], [])


class MemberCheckApiTest(TestCase):
    def setUp(self):
        cache.clear()  # 节流按 IP 计数：隔离每个用例（locmem 缓存跨用例共享）。

    def test_check_valid_signature(self):
        make_row()
        code = "26020001"
        resp = self.client.get(f"/auth/member/check/?c={code}&s={make_signature(code)}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["name"], "张三")
        self.assertEqual(data["cohort"], 2)
        self.assertEqual(data["group"], "摄影")
        self.assertNotIn("phone", data)

    def test_check_tampered_or_missing_signature(self):
        make_row()
        self.assertEqual(self.client.get("/auth/member/check/?c=26020001&s=deadbeef").status_code, 404)
        self.assertEqual(self.client.get("/auth/member/check/?c=26020001").status_code, 404)
        self.assertEqual(self.client.get("/auth/member/check/").status_code, 404)

    def test_check_unknown_code_with_valid_signature(self):
        resp = self.client.get(f"/auth/member/check/?c=99999999&s={make_signature('99999999')}")
        self.assertEqual(resp.status_code, 404)

    def test_check_throttled(self):
        code = "26020001"
        url = f"/auth/member/check/?c={code}&s={make_signature(code)}"
        for _ in range(60):
            self.assertEqual(self.client.get(url).status_code, 404)  # 码不存在但已计数
        self.assertEqual(self.client.get(url).status_code, 429)


class RegisterAutoLoginTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_register_creates_session_and_logged_in_flag(self):
        resp = self.client.post("/auth/register/", data=valid_payload())
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(resp.json()["logged_in"])
        me = self.client.get("/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["username"], "newbie")
        user = User.objects.get(username="newbie")
        self.assertTrue(UserSession.objects.filter(user=user).exists())


class ClaimServiceTest(TestCase):
    def test_candidates_and_service_direct(self):
        user = make_user(real_name="张 三")
        row = make_row()
        self.assertEqual([r.id for r in claim_candidates(user)], [row.id])
        bound = claim_identity(user, row.id, "9198")
        self.assertEqual(bound.user_id, user.id)
