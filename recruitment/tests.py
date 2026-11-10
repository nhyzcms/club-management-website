from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from activities.models import Questionnaire, QuestionnaireResponse
from recruitment.models import RecruitmentNotice


def _editor():
    user = User.objects.create_user(username="editor", password="x")
    user.user_permissions.add(Permission.objects.get(codename="manage_aboutpage"))
    return user


DEVICE = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class RecruitmentLandingTest(TestCase):
    def test_anon_reads_notice_and_schema(self):
        resp = APIClient().get("/recruitment/", HTTP_X_DEVICE_ID=DEVICE)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("notice", resp.data)
        self.assertIn("schema", resp.data)
        self.assertFalse(resp.data["already_responded"])
        self.assertIn("pages", resp.data["schema"])
        self.assertTrue(any(t.get("type") == "skip" for t in resp.data["schema"].get("triggers") or []))


class NoticeAckGateTest(TestCase):
    def setUp(self):
        cache.clear()  # 限流缓存跨用例残留会误伤（M-3）

    def test_submit_without_ack_rejected(self):
        resp = APIClient().post(
            "/recruitment/responses/",
            {"answers": {"grade": "高一"}, "notice_acknowledged": False},
            format="json",
            HTTP_X_DEVICE_ID=DEVICE,
        )
        self.assertEqual(resp.status_code, 400)

    def test_submit_with_ack_persists(self):
        resp = APIClient().post(
            "/recruitment/responses/",
            {"answers": {"grade": "高一", "intro": "你好"}, "notice_acknowledged": True},
            format="json",
            HTTP_X_DEVICE_ID=DEVICE,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["ok"])
        q = Questionnaire.get_join()
        self.assertEqual(q.responses.count(), 1)
        self.assertEqual(q.responses.get().answers["grade"], "高一")

    def test_guest_same_device_up_to_five_submissions(self):
        """游客同设备最多提交 5 次；第 6 次拒绝。"""
        payload = {"answers": {"grade": "高一", "intro": "你好"}, "notice_acknowledged": True}
        client = APIClient()
        for i in range(5):
            resp = client.post("/recruitment/responses/", payload, format="json", HTTP_X_DEVICE_ID=DEVICE)
            self.assertEqual(resp.status_code, 201, f"第 {i + 1} 次应成功")
        again = client.post("/recruitment/responses/", payload, format="json", HTTP_X_DEVICE_ID=DEVICE)
        self.assertEqual(again.status_code, 400)
        self.assertEqual(Questionnaire.get_join().responses.count(), 5)

    def test_logged_in_user_up_to_five_submissions(self):
        """登录用户同样最多 5 次。"""
        payload = {"answers": {"grade": "高二", "intro": "你好"}, "notice_acknowledged": True}
        client = APIClient()
        client.force_authenticate(User.objects.create_user(username="stu", password="x"))
        for i in range(5):
            resp = client.post("/recruitment/responses/", payload, format="json")
            self.assertEqual(resp.status_code, 201, f"第 {i + 1} 次应成功")
        again = client.post("/recruitment/responses/", payload, format="json")
        self.assertEqual(again.status_code, 400)
        self.assertIn("上限", again.data["detail"])

    def test_landing_reports_responded_count(self):
        """landing 返回已提交次数与上限（前端据此显示提示与限流）。"""
        payload = {"answers": {"grade": "高一"}, "notice_acknowledged": True}
        client = APIClient()
        client.post("/recruitment/responses/", payload, format="json", HTTP_X_DEVICE_ID=DEVICE)
        resp = client.get("/recruitment/", HTTP_X_DEVICE_ID=DEVICE)
        self.assertEqual(resp.data["responded_count"], 1)
        self.assertEqual(resp.data["max_submissions"], 5)
        self.assertTrue(resp.data["already_responded"])

    def test_guest_missing_device_id_rejected(self):
        resp = APIClient().post(
            "/recruitment/responses/",
            {"answers": {"grade": "高一", "intro": "你好"}, "notice_acknowledged": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_empty_answers_rejected(self):
        resp = APIClient().post(
            "/recruitment/responses/",
            {"answers": {}, "notice_acknowledged": True},
            format="json",
            HTTP_X_DEVICE_ID=DEVICE,
        )
        self.assertEqual(resp.status_code, 400)


class SchemaPersistTest(TestCase):
    def test_editor_updates_schema(self):
        client = APIClient()
        client.force_authenticate(_editor())
        schema = {"title": "新问卷", "pages": [{"name": "p", "elements": [{"type": "text", "name": "n"}]}]}
        resp = client.put("/recruitment/schema/", {"schema": schema}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Questionnaire.get_join().schema["title"], "新问卷")

    def test_editor_updates_notice(self):
        client = APIClient()
        client.force_authenticate(_editor())
        resp = client.put("/recruitment/notice/", {"content": "<p>2026 招生</p>"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(RecruitmentNotice.objects.get_solo().content, "<p>2026 招生</p>")
        self.assertEqual(resp.data["content"], "<p>2026 招生</p>")

    def test_invalid_schema_rejected(self):
        client = APIClient()
        client.force_authenticate(_editor())
        resp = client.put("/recruitment/schema/", {"schema": {"title": "无 pages"}}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_stranger_cannot_edit_schema(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user(username="u", password="x"))
        resp = client.put("/recruitment/schema/", {"schema": {"pages": []}}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_stranger_cannot_list_responses(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user(username="u", password="x"))
        self.assertEqual(client.get("/recruitment/responses/").status_code, 403)


class JoinAnswerThrottleTest(TestCase):
    """M-3 回归：加入问卷按 IP 限流，轮换设备号也灌不爆。"""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def test_ip_hourly_cap(self):
        for i in range(10):
            resp = self.client.post(
                "/recruitment/responses/",
                {"answers": {"grade": "高一"}, "notice_acknowledged": True},
                format="json",
                HTTP_X_DEVICE_ID=f"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee{i:02d}",
                REMOTE_ADDR="203.0.113.30",
            )
            self.assertIn(resp.status_code, (201, 400))
        resp = self.client.post(
            "/recruitment/responses/",
            {"answers": {"grade": "高一"}, "notice_acknowledged": True},
            format="json",
            HTTP_X_DEVICE_ID="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee99",
            REMOTE_ADDR="203.0.113.30",
        )
        self.assertEqual(resp.status_code, 429)
