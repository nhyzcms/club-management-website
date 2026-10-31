"""自助认领 / 扫码校验 / 注册即登录（ADR-0025 的 API 层）。

覆盖：候选与绑定状态接口、认领（成功 / 错四位 / 姓名不符 / 重复 / 无电话 /
节流 / 开关关闭）、公开校验（签名 / 篡改 / 枚举 / 限流 / 字段最小化）、
注册成功后自动登录（会话 + logged_in 标记）。
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

from .testing import make_profile

from accounts.member_codes import make_signature
from accounts.member_roster import claim_candidates, claim_identity, commit_import, parse_roster
from accounts.models import AccountIdentity, MemberIdentity, Profile, UserSession
from accounts.tests_register import valid_payload
from common.models import SiteSettings


def make_row(name="张三", cohort=2, phone="11451419198", code="26020001", card_no=""):
    return MemberIdentity.objects.create(
        name=name, admit_year=2026, cohort=cohort, phone=phone, code=code,
        card_no=card_no,
    )


def make_user(username="u1", real_name="张三"):
    user = User.objects.create_user(username=username, password="StrongPass123!")
    make_profile(user=user, real_name=real_name)
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

class CardNoSyncTest(TestCase):
    """校牌号在「注册资料 Profile.card_no」与「名册行 MemberIdentity.card_no」之间同步（同一个值）。"""

    CSV_HEADER = "姓名,班级,校牌号,入学年份,入社时间,届数,性别,电话号码\n"

    def setUp(self):
        cache.clear()

    def test_bound_payload_has_card_no_candidates_do_not(self):
        user = make_user()
        row = make_row(card_no="A001")
        self.client.force_login(user)
        data = self.client.get("/auth/member/").json()
        self.assertNotIn("card_no", data["candidates"][0])  # 候选不下发校牌号
        row.user = user
        row.save()
        data = self.client.get("/auth/member/").json()
        self.assertEqual(data["bound"]["card_no"], "A001")  # 自己的档案可见

    def test_claim_fills_blank_row_card_no_from_profile(self):
        user = make_user()
        AccountIdentity.objects.filter(user=user).update(pending_card_no="A009")
        row = make_row()
        self.client.force_login(user)
        resp = self.client.post(
            "/auth/member/claim/",
            data={"identity_id": row.id, "phone_last4": "9198"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        row.refresh_from_db()
        self.assertEqual(row.card_no, "A009")

    def test_claim_roster_card_no_wins(self):
        user = make_user()
        AccountIdentity.objects.filter(user=user).update(pending_card_no="B002")
        row = make_row(card_no="A001")
        self.client.force_login(user)
        self.client.post(
            "/auth/member/claim/",
            data={"identity_id": row.id, "phone_last4": "9198"},
            content_type="application/json",
        )
        user.profile.refresh_from_db()
        # B4：名册是唯一权威，账号侧的「待绑定暂存」在绑定后清空
        self.assertEqual(user.identity_record.pending_card_no, "")
        self.assertEqual(MemberIdentity.objects.get(pk=row.pk).card_no, "A001")

    def test_import_writes_profile_card_no_back_to_row(self):
        user = make_user()  # 张三，注册时填了校牌号但名册还没导入
        AccountIdentity.objects.filter(user=user).update(pending_card_no="A001")
        content = (self.CSV_HEADER + "张三,1,,2026,20260303,2,男,11451419198\n").encode("utf-8-sig")
        commit_import(parse_roster("a.csv", content), file_name="a.csv")
        row = MemberIdentity.objects.get(name="张三")
        self.assertEqual(row.card_no, "A001")
        self.assertEqual(row.user_id, user.id)  # 同时按姓名自动匹配绑定
