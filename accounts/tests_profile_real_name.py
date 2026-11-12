"""资料页实名 / 校牌号自助补录（2026-11-11）。

覆盖：
- 本人资料接口返回实名、可编辑态与锁定日期；
- 空姓名可补录，补录后一年内不可再改；满一年可改一次；
- 校牌号只允许从空补录一次；已绑定名册时以名册为准；
- 姓名 + 校牌号唯一命中名册时自动绑定（与注册同一条口径）；
- 管理员在后台可更正真实姓名，且不占用用户的年度机会。
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountIdentity, MemberIdentity
from accounts.testing import make_profile


def _row(name="张三", card_no="2601001", code="26020001"):
    return MemberIdentity.objects.create(
        name=name, admit_year=2026, cohort=2, code=code, card_no=card_no,
    )


class ProfileRealNameApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="real_name_u", password="x")
        make_profile(user=self.user, real_name="", identity="student")
        self.client.force_login(self.user)

    def _identity(self):
        return AccountIdentity.objects.get(user=self.user)

    def _set_identity(self, **fields):
        AccountIdentity.objects.filter(user=self.user).update(**fields)

    def test_payload_exposes_empty_state_for_filling(self):
        data = self.client.get("/auth/profile/").json()["profile"]
        self.assertEqual(data["real_name"], "")
        self.assertTrue(data["real_name_editable"])
        self.assertIsNone(data["real_name_locked_until"])
        self.assertEqual(data["card_no"], "")
        self.assertTrue(data["card_no_editable"])

    def test_fill_name_then_locked_for_a_year(self):
        resp = self.client.post("/auth/profile/update/", {"real_name": "  李四  "})
        self.assertEqual(resp.status_code, 200, resp.content)
        identity = self._identity()
        self.assertEqual(identity.real_name, "李四")
        self.assertIsNotNone(identity.real_name_changed_at)
        data = resp.json()["profile"]
        self.assertEqual(data["real_name"], "李四")
        self.assertFalse(data["real_name_editable"])
        self.assertIsNotNone(data["real_name_locked_until"])

        # 锁定期内再改 → 400，原值保持不变
        resp = self.client.post("/auth/profile/update/", {"real_name": "王五"})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(self._identity().real_name, "李四")

    def test_can_change_again_after_one_year(self):
        self._set_identity(
            real_name="张三",
            real_name_changed_at=timezone.now() - timedelta(days=366),
        )
        resp = self.client.post("/auth/profile/update/", {"real_name": "张三丰"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._identity().real_name, "张三丰")
        # 改过一次后又锁一年
        resp = self.client.post("/auth/profile/update/", {"real_name": "张三"})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_empty_name_does_not_clear_existing(self):
        self._set_identity(real_name="张三")
        resp = self.client.post("/auth/profile/update/", {"real_name": "  "})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(self._identity().real_name, "张三")

    def test_card_no_fill_only_from_empty(self):
        identity = self._identity()
        identity.pending_card_no = "111"
        identity.save(update_fields=["pending_card_no"])
        resp = self.client.post("/auth/profile/update/", {"card_no": "222"})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(self._identity().pending_card_no, "111")

    def test_card_no_not_allowed_for_teacher(self):
        self._set_identity(identity="teacher")
        resp = self.client.post("/auth/profile/update/", {"card_no": "123"})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_name_and_card_unique_hit_auto_binds_roster(self):
        row = _row(name="张三", card_no="2601001")
        resp = self.client.post(
            "/auth/profile/update/",
            {"real_name": "张三", "card_no": "2601001"},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        row.refresh_from_db()
        self.assertEqual(row.user_id, self.user.pk)
        self.assertEqual(row.bind_method, MemberIdentity.BIND_REGISTER)
        data = resp.json()["profile"]
        self.assertEqual(data["card_no"], "2601001")
        self.assertFalse(data["card_no_editable"])
        self.assertEqual(data["card_no_locked_reason"], "member")

    def test_bound_roster_card_cannot_be_changed(self):
        row = _row(name="张三", card_no="2601001")
        row.user = self.user
        row.save()
        resp = self.client.post("/auth/profile/update/", {"card_no": "999"})
        self.assertEqual(resp.status_code, 400, resp.content)
        row.refresh_from_db()
        self.assertEqual(row.card_no, "2601001")


class AdminRealNameEditTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_rn", email="a@example.com", password="x",
        )
        self.target = User.objects.create_user(username="target_rn", password="x")
        make_profile(user=self.target, real_name="旧名")
        self.client.force_login(self.admin)

    def test_admin_can_change_real_name_inline(self):
        identity = AccountIdentity.objects.get(user=self.target)
        url = reverse("admin:auth_user_change", args=[self.target.pk])
        data = {
            "username": self.target.username,
            "email": self.target.email,
            "first_name": "",
            "last_name": "",
            "is_active": "on",
            "date_joined_0": "2026-01-01",
            "date_joined_1": "00:00:00",
            "profile-TOTAL_FORMS": "0",
            "profile-INITIAL_FORMS": "0",
            "profile-MIN_NUM_FORMS": "0",
            "profile-MAX_NUM_FORMS": "1",
            "lifecycle-TOTAL_FORMS": "0",
            "lifecycle-INITIAL_FORMS": "0",
            "lifecycle-MIN_NUM_FORMS": "0",
            "lifecycle-MAX_NUM_FORMS": "1",
            "verifications-TOTAL_FORMS": "0",
            "verifications-INITIAL_FORMS": "0",
            "verifications-MIN_NUM_FORMS": "0",
            "verifications-MAX_NUM_FORMS": "1000",
            "member_equipment-TOTAL_FORMS": "0",
            "member_equipment-INITIAL_FORMS": "0",
            "member_equipment-MIN_NUM_FORMS": "0",
            "member_equipment-MAX_NUM_FORMS": "1000",
            "identity_record-TOTAL_FORMS": "1",
            "identity_record-INITIAL_FORMS": "1",
            "identity_record-MIN_NUM_FORMS": "0",
            "identity_record-MAX_NUM_FORMS": "1",
            "identity_record-0-id": str(identity.pk),
            "identity_record-0-real_name": "更正名",
        }
        resp = self.client.post(url, data, follow=True)
        self.assertEqual(resp.status_code, 200, resp.content)
        identity.refresh_from_db()
        self.assertEqual(identity.real_name, "更正名")
        # 管理员修改不写「本人自助修改」时间，不占用用户的年度机会。
        self.assertIsNone(identity.real_name_changed_at)
