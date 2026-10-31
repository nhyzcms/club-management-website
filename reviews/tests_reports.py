from common.targets import target_of
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission, User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.test_helpers import grant_verification
from messaging.models import Comment, CommentThread
from messaging.services import thread_for
from news.models import News
from reviews.models import ReportCase, ReportFiling, Review, UserMute
from reviews.test_helpers import approve_news


def _perm(user, *codenames):
    for raw in codenames:
        app, code = raw.split(".", 1)
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=code))
    return user


def _verified(name):
    return grant_verification(User.objects.create_user(username=name, password="x"))


class ReportCaseApiTest(TestCase):
    def setUp(self):
        cache.clear()
        self.author = _verified("author")
        self.reporter = _verified("reporter")
        self.other = _verified("other")
        self.handler = _perm(_verified("handler"), "reviews.handle_report")
        self.client = APIClient()
        self.news = approve_news(News.objects.create(
            title="public-news", author=self.author, is_published=True,
        ))
        self.draft = News.objects.create(title="draft", author=self.author, is_published=False)

    def _file(self, user, **kwargs):
        self.client.force_authenticate(user)
        payload = {
            "target_type": "news",
            "target_id": self.news.pk,
            "reason": "违规",
        }
        payload.update(kwargs)
        return self.client.post("/reviews/reports/", payload, format="json")

    def test_file_opens_case(self):
        resp = self._file(self.reporter)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], ReportCase.STATUS_OPEN)
        self.assertEqual(ReportCase.objects.filter(target=target_of(self.news), status=ReportCase.STATUS_OPEN).count(), 1)
        self.assertEqual(ReportFiling.objects.filter(reporter=self.reporter).count(), 1)

    def test_second_reporter_attaches(self):
        self.assertEqual(self._file(self.reporter).status_code, 201)
        resp = self._file(self.other, reason="我也看到了")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(ReportCase.objects.filter(target=target_of(self.news)).count(), 1)
        case = ReportCase.objects.get(target=target_of(self.news))
        self.assertEqual(case.filings.count(), 2)

    def test_duplicate_reporter_400(self):
        self.assertEqual(self._file(self.reporter).status_code, 201)
        resp = self._file(self.reporter, reason="再举一次")
        self.assertEqual(resp.status_code, 400)

    def test_closed_case_opens_new(self):
        self.assertEqual(self._file(self.reporter).status_code, 201)
        case = ReportCase.objects.get(target=target_of(self.news))
        self.client.force_authenticate(self.handler)
        self.assertEqual(
            self.client.post(
                f"/reviews/reports/{case.pk}/dismiss/",
                {"comment": "不成立"},
                format="json",
            ).status_code,
            200,
        )
        resp = self._file(self.other, reason="新一轮")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(ReportCase.objects.filter(target=target_of(self.news)).count(), 2)
        self.assertEqual(ReportCase.objects.filter(target=target_of(self.news), status=ReportCase.STATUS_OPEN).count(), 1)

    def test_self_report_400(self):
        resp = self._file(self.author)
        self.assertEqual(resp.status_code, 400)

    def test_unpublished_target_400(self):
        resp = self._file(self.reporter, target_id=self.draft.pk)
        self.assertEqual(resp.status_code, 400)

    def test_unverified_403(self):
        guest = User.objects.create_user(username="guest", password="x")
        resp = self._file(guest)
        self.assertEqual(resp.status_code, 403)

    def test_dismiss_requires_reason(self):
        self.assertEqual(self._file(self.reporter).status_code, 201)
        case = ReportCase.objects.get(target=target_of(self.news))
        self.client.force_authenticate(self.handler)
        resp = self.client.post(f"/reviews/reports/{case.pk}/dismiss/", {"comment": ""}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_handler_without_moderate_can_uphold_remove(self):
        self.assertEqual(self._file(self.reporter).status_code, 201)
        case = ReportCase.objects.get(target=target_of(self.news))
        self.assertFalse(self.handler.has_perm("reviews.moderate"))
        self.client.force_authenticate(self.handler)
        resp = self.client.post(
            f"/reviews/reports/{case.pk}/uphold/",
            {"comment": "下架"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.news.refresh_from_db()
        self.assertEqual(
            Review.objects.get(target=target_of(self.news)).status, Review.STATUS_REMOVED,
        )
        case.refresh_from_db()
        self.assertEqual(case.status, ReportCase.STATUS_UPHELD)

    def test_already_removed_is_idempotent(self):
        self.assertEqual(self._file(self.reporter).status_code, 201)
        Review.objects.filter(target=target_of(self.news)).update(
            status=Review.STATUS_REMOVED,
        )
        case = ReportCase.objects.get(target=target_of(self.news))
        self.client.force_authenticate(self.handler)
        resp = self.client.post(f"/reviews/reports/{case.pk}/uphold/", {"comment": "ok"}, format="json")
        self.assertEqual(resp.status_code, 200)
        case.refresh_from_db()
        self.assertEqual(case.status, ReportCase.STATUS_UPHELD)

    def test_daily_cap(self):
        from common.policy import SitePolicy, get_policy
        policy = get_policy()
        capped = SitePolicy(**{**policy.__dict__, "reports_per_user_per_day": 1})
        with patch("reviews.throttles.get_policy", return_value=capped):
            self.assertEqual(self._file(self.reporter).status_code, 201)
            news2 = approve_news(News.objects.create(
                title="n2", author=self.author, is_published=True,
            ))
            resp = self._file(self.reporter, target_id=news2.pk, reason="第二条")
            self.assertEqual(resp.status_code, 429)


class ReportCommentAndUserTest(TestCase):
    def setUp(self):
        cache.clear()
        self.author = _verified("author")
        self.reporter = _verified("reporter")
        self.handler = _perm(_verified("handler"), "reviews.handle_report")
        self.client = APIClient()
        self.news = approve_news(News.objects.create(
            title="n", author=self.author, is_published=True,
        ))
        self.thread = thread_for(self.news)
        self.comment = Comment.objects.create(
            thread=self.thread, author=self.author, content="bad comment",
        )
        self.target_user = _verified("target")

    def test_uphold_tombs_comment_without_thread_perm(self):
        self.client.force_authenticate(self.reporter)
        resp = self.client.post(
            "/reviews/reports/",
            {"target_type": "comment", "target_id": self.comment.pk, "reason": "骂人"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(self.handler.has_perm("messaging.manage_comment_thread"))
        self.client.force_authenticate(self.handler)
        resp = self.client.post(
            f"/reviews/reports/{resp.data['id']}/uphold/",
            {"comment": "删"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.comment.refresh_from_db()
        self.assertIsNotNone(self.comment.deleted_at)
        self.assertEqual(self.comment.deleted_by_id, self.handler.pk)

    def test_deleted_comment_cannot_be_filed(self):
        self.comment.deleted_at = timezone.now()
        self.comment.save()
        self.client.force_authenticate(self.reporter)
        resp = self.client.post(
            "/reviews/reports/",
            {"target_type": "comment", "target_id": self.comment.pk, "reason": "还举"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_uphold_mutes_user_without_mute_perm(self):
        self.assertFalse(self.handler.has_perm("reviews.mute_user"))
        self.client.force_authenticate(self.reporter)
        resp = self.client.post(
            "/reviews/reports/",
            {"target_type": "user", "target_id": self.target_user.pk, "reason": "骚扰"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.client.force_authenticate(self.handler)
        ends = (timezone.now() + timedelta(days=3)).isoformat()
        resp = self.client.post(
            f"/reviews/reports/{resp.data['id']}/uphold/",
            {"comment": "禁三天", "ends_at": ends},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(UserMute.objects.filter(user=self.target_user, lifted_at__isnull=True).exists())

    def test_staff_without_handle_report_cannot_list(self):
        self.client.force_authenticate(self.reporter)
        resp = self.client.get("/reviews/reports/")
        self.assertEqual(resp.status_code, 403)
