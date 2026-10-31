from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from messaging.models import Notification
from reviews.models import Feedback


def _president(user):
    g, _ = Group.objects.get_or_create(name="社长")
    user.groups.add(g)
    return user


class FeedbackSubmitTest(TestCase):
    def setUp(self):
        cache.clear()
        self.member = User.objects.create_user(username="member", password="x")
        self.client = APIClient()

    def test_attributed_feedback_records_creator(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post(
            "/reviews/feedbacks/submit/",
            {
                "title": "建议",
                "description": "内容",
                "category": "suggestion",
                "disclose_identity": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["creator"]["username"], "member")
        row = Feedback.objects.get(pk=resp.data["id"])
        self.assertEqual(row.creator, self.member)
        self.assertEqual(row.status, Feedback.STATUS_PENDING)
        self.assertEqual(row.category, Feedback.CATEGORY_SUGGESTION)

    def test_anonymous_feedback_has_no_creator(self):
        resp = self.client.post(
            "/reviews/feedbacks/submit/",
            {"title": "匿名", "description": "……", "category": "complaint"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.data["creator"])
        self.assertIsNone(Feedback.objects.get(pk=resp.data["id"]).creator)

    def test_logged_in_choosing_anonymous_has_no_creator(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post(
            "/reviews/feedbacks/submit/",
            {"title": "匿名", "description": "……", "category": "other"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.data["creator"])

    def test_disclose_without_login_rejected(self):
        resp = self.client.post(
            "/reviews/feedbacks/submit/",
            {
                "title": "署名", "description": "……", "category": "suggestion",
                "disclose_identity": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_report_is_not_a_feedback_category(self):
        resp = self.client.post(
            "/reviews/feedbacks/submit/",
            {"title": "旧举报", "description": "……", "category": "report"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="secret")
    def test_anonymous_rejected_without_turnstile_when_enabled(self):
        resp = self.client.post(
            "/reviews/feedbacks/submit/",
            {"title": "匿名", "description": "……", "category": "complaint"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("人机校验", str(resp.data["detail"]))
        self.assertFalse(Feedback.objects.exists())

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="secret")
    def test_logged_in_skips_turnstile(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post(
            "/reviews/feedbacks/submit/",
            {"title": "匿名", "description": "……", "category": "other"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)


class FeedbackCloseTest(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(username="member", password="x")
        self.president = _president(User.objects.create_user(username="pres", password="x"))
        self.client = APIClient()
        self.row = Feedback.objects.create(
            title="f", category="suggestion", status="pending", creator=self.member,
        )

    def test_non_holder_cannot_close(self):
        self.client.force_authenticate(self.member)
        resp = self.client.post(f"/reviews/feedbacks/{self.row.pk}/close/", {"note": "ok"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_holder_can_close_and_notifies_creator(self):
        self.client.force_authenticate(self.president)
        resp = self.client.post(
            f"/reviews/feedbacks/{self.row.pk}/close/",
            {"note": "已线下跟进"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, Feedback.STATUS_CLOSED)
        self.assertEqual(self.row.moderation_note, "已线下跟进")
        note = Notification.objects.get(recipient=self.member, category="review", event="closed")
        self.assertEqual(note.payload["id"], self.row.pk)
        self.assertEqual(note.payload["url"], f"/feedback/{self.row.pk}")

    def test_anonymous_close_does_not_notify(self):
        self.row.creator = None
        self.row.save()
        self.client.force_authenticate(self.president)
        resp = self.client.post(f"/reviews/feedbacks/{self.row.pk}/close/", {"note": "ok"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Notification.objects.filter(event="closed").exists())

    def test_owner_can_retrieve(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get(f"/reviews/feedbacks/{self.row.pk}/")
        self.assertEqual(resp.status_code, 200)

    def test_staff_can_list(self):
        self.client.force_authenticate(self.president)
        resp = self.client.get("/reviews/feedbacks/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.data["count"], 1)

    def test_member_cannot_list(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get("/reviews/feedbacks/")
        self.assertEqual(resp.status_code, 403)


class FeedbackUserThrottleTest(TestCase):
    """M-3 回归：已登录用户反馈也限流（此前只限匿名）。"""

    def setUp(self):
        cache.clear()
        self.member = User.objects.create_user(username="fb_throttle", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.member)

    def tearDown(self):
        cache.clear()

    def test_user_hourly_cap(self):
        for i in range(10):
            resp = self.client.post(
                "/reviews/feedbacks/submit/",
                {"title": f"t{i}", "description": "x", "category": "other"},
                format="json",
            )
            self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.client.post(
            "/reviews/feedbacks/submit/",
            {"title": "overflow", "description": "x", "category": "other"},
            format="json",
        )
        self.assertEqual(resp.status_code, 429)
