"""社员公开查询（/auth/member/lookup/）：字段最小化、精确匹配、分档额度。"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import MemberIdentity, Profile, Verification
from .testing import make_profile


def _verify(user):
    """把账号标成已认证（人工通道、一年有效）。"""
    Verification.objects.create(
        user=user,
        channel=Verification.CHANNEL_MANUAL,
        status=Verification.STATUS_APPROVED,
        expires_at=timezone.now() + timedelta(days=365),
    )
    return user


def _identity(name, code, *, user=None, cohort=1, **kwargs):
    return MemberIdentity.objects.create(
        name=name, code=code, cohort=cohort, admit_year=2025, user=user, **kwargs
    )


class MemberLookupTest(TestCase):
    URL = "/auth/member/lookup/"

    def setUp(self):
        cache.clear()  # 额度计数走缓存：每个测试从干净窗口开始
        self.client = APIClient()
        self.row = _identity("张三", "26010201", card_no="A001", phone="13800001111")

    def post(self, q, **extra):
        return self.client.post(self.URL, {"q": q}, format="json", **extra)

    # ---- 查询与字段 ----
    def test_lookup_by_code_returns_public_fields_only(self):
        resp = self.post("26010201")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["found"])
        self.assertEqual(len(data["results"]), 1)
        item = data["results"][0]
        self.assertEqual(item["name"], "张三")
        self.assertEqual(item["code"], "26010201")
        self.assertEqual(item["cohort"], 1)
        self.assertEqual(item["status"], "active")
        # 电话 / 校牌号等私有字段绝不下发
        for forbidden in ("phone", "card_no", "class_no", "user", "id"):
            self.assertNotIn(forbidden, item)

    def test_lookup_by_exact_name(self):
        resp = self.post("张三")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"][0]["code"], "26010201")

    def test_partial_name_is_not_a_match(self):
        """不做模糊 / 前缀匹配——否则等于把整本名册交出去。"""
        self.assertFalse(self.post("张").json()["found"])
        self.assertFalse(self.post("张三丰").json()["found"])

    def test_unknown_query_consumes_quota_and_counts(self):
        """未命中同样计数，防止无限试错。"""
        for _ in range(3):
            self.assertEqual(self.post("查无此人").status_code, 200)
        resp = self.post("查无此人")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("上限", resp.json()["error"])

    def test_duplicate_names_return_all_matches(self):
        _identity("张三", "25010202", cohort=0)
        resp = self.post("张三").json()
        self.assertEqual(len(resp["results"]), 2)

    # ---- 额度分档 ----
    def test_anon_limited_to_three_per_day(self):
        for _ in range(3):
            self.assertEqual(self.post("张三").status_code, 200)
        resp = self.post("张三")
        self.assertEqual(resp.status_code, 429)
        quota = resp.json()["quota"]
        self.assertEqual(quota["limit"], 3)
        self.assertEqual(quota["used"], 3)
        self.assertEqual(quota["remaining"], 0)
        self.assertGreater(resp.json()["retry_after"], 0)

    def test_quota_get_does_not_consume(self):
        for _ in range(5):
            resp = self.client.get(self.URL)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["quota"]["used"], 0)
        self.assertEqual(self.post("张三").status_code, 200)

    def test_unverified_user_limited_to_ten(self):
        user = User.objects.create_user(username="pending", password="x")
        self.client.force_login(user)
        for _ in range(10):
            self.assertEqual(self.post("张三").status_code, 200)
        resp = self.post("张三")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["quota"]["limit"], 10)

    def test_verified_non_member_limited_to_twenty(self):
        user = _verify(User.objects.create_user(username="verified", password="x"))
        self.client.force_login(user)
        for _ in range(20):
            self.assertEqual(self.post("张三").status_code, 200)
        resp = self.post("张三")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["quota"]["limit"], 20)

    def test_member_is_unlimited(self):
        user = User.objects.create_user(username="member", password="x")
        _identity("李四", "25010205", user=user)
        self.client.force_login(user)
        for _ in range(30):
            self.assertEqual(self.post("张三").status_code, 200)
        self.assertIsNone(self.client.get(self.URL).json()["quota"]["limit"])

    def test_verified_teacher_is_unlimited(self):
        user = _verify(User.objects.create_user(username="teacher", password="x"))
        make_profile(user=user, identity="teacher")
        self.client.force_login(user)
        for _ in range(30):
            self.assertEqual(self.post("张三").status_code, 200)
        self.assertIsNone(self.client.get(self.URL).json()["quota"]["limit"])

    def test_staff_and_superuser_are_unlimited(self):
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        self.client.force_login(staff)
        for _ in range(25):
            self.assertEqual(self.post("张三").status_code, 200)

        superuser = User.objects.create_superuser(
            username="root", password="x", email="root@example.com"
        )
        self.client.force_login(superuser)
        for _ in range(25):
            self.assertEqual(self.post("张三").status_code, 200)

    def test_quota_is_per_user_not_shared_with_anon(self):
        """匿名额度用尽不影响登录用户（反之亦然）。"""
        for _ in range(4):
            self.post("张三")
        user = User.objects.create_user(username="other", password="x")
        self.client.force_login(user)
        self.assertEqual(self.post("张三").status_code, 200)

    def test_empty_query_rejected_without_consuming(self):
        resp = self.post("   ")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.client.get(self.URL).json()["quota"]["used"], 0)
