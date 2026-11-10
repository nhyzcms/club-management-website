"""我的设备（2026-11-10）：社员登记可带到活动的物品。

覆盖：社员 CRUD / 物品名校验 / 每人上限 / 越权访问 / 非社员与未登录拒绝 /
个人主页返回 is_member 供前端决定是否显示入口。
"""
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import MemberEquipment, MemberIdentity


def make_member(username, name="张三", cohort=2, code="26020001"):
    user = User.objects.create_user(username=username, password="x")
    MemberIdentity.objects.create(name=name, admit_year=2026, cohort=cohort, code=code, user=user)
    return user


class MemberEquipmentApiTest(TestCase):
    def setUp(self):
        self.member = make_member("member-a", name="张三", code="26020001")
        self.other = make_member("member-b", name="李四", code="26020002")
        self.outsider = User.objects.create_user(username="outsider", password="x")
        self.list_url = reverse("member_equipment")

    def _post(self, payload):
        return self.client.post(
            self.list_url, data=json.dumps(payload), content_type="application/json",
        )

    def test_member_can_create_and_list(self):
        self.client.force_login(self.member)
        resp = self._post({"name": "  佳能 R6  "})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["item"]["name"], "佳能 R6")
        self.assertEqual(MemberEquipment.objects.filter(user=self.member).count(), 1)

        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["limit"], 30)
        self.assertEqual([row["name"] for row in data["items"]], ["佳能 R6"])

    def test_name_validation(self):
        self.client.force_login(self.member)
        for payload in ({"name": ""}, {"name": "   "}, {}, {"name": "相" * 101}):
            self.assertEqual(self._post(payload).status_code, 400, payload)

    def test_limit_per_member(self):
        self.client.force_login(self.member)
        MemberEquipment.objects.bulk_create(
            [MemberEquipment(user=self.member, name=f"设备{i}") for i in range(30)]
        )
        self.assertEqual(self._post({"name": "第 31 件"}).status_code, 400)

    def test_rename_and_delete_own(self):
        self.client.force_login(self.member)
        row = MemberEquipment.objects.create(user=self.member, name="旧名字")
        detail = reverse("member_equipment_detail", args=[row.pk])

        resp = self.client.patch(
            detail, data=json.dumps({"name": "新名字"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.name, "新名字")

        self.assertEqual(self.client.delete(detail).status_code, 200)
        self.assertFalse(MemberEquipment.objects.filter(pk=row.pk).exists())

    def test_cannot_touch_other_members_item(self):
        row = MemberEquipment.objects.create(user=self.other, name="别人的相机")
        self.client.force_login(self.member)
        detail = reverse("member_equipment_detail", args=[row.pk])
        resp = self.client.patch(
            detail, data=json.dumps({"name": "抢过来"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.client.delete(detail).status_code, 404)
        row.refresh_from_db()
        self.assertEqual(row.name, "别人的相机")

    def test_non_member_is_forbidden(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self._post({"name": "相机"}).status_code, 403)
        self.assertFalse(MemberEquipment.objects.exists())

    def test_login_required(self):
        self.assertEqual(self.client.get(self.list_url).status_code, 302)

    def test_profile_reports_is_member(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse("user_profile", args=[self.member.id]))
        self.assertTrue(resp.json()["viewer"]["is_member"])

        resp = self.client.get(reverse("user_profile", args=[self.outsider.id]))
        self.assertFalse(resp.json()["viewer"]["is_member"])
