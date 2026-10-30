"""Django admin review change form embeds the target SPA page."""
import copy
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.test import Client, RequestFactory, TestCase

from news.models import News
from reviews.lifecycle import open_review
from reviews.models import Review

from .admin import ReviewAdmin


class ReviewAdminPreviewTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("adm", "a@e.com", "x")
        self.author = User.objects.create_user("author", password="x")
        self.news = News.objects.create(title="后台预览稿", content="<p>正文</p>", author=self.author)
        self.review = open_review(news=self.news, actor=self.author)

    def test_spa_allows_same_origin_framing(self):
        # CI backend job has no webpack build; frontend/dist/index.html is absent.
        tmpl_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmpl_dir, ignore_errors=True))
        (tmpl_dir / "index.html").write_text("<html></html>", encoding="utf-8")
        templates = copy.deepcopy(settings.TEMPLATES)
        templates[0]["DIRS"] = [str(tmpl_dir), *templates[0]["DIRS"]]
        with self.settings(TEMPLATES=templates):
            resp = Client().get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")

    def test_change_form_iframes_news_page(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(f"/admin/reviews/review/{self.review.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("<iframe", body)
        self.assertIn(f"/#/news/{self.news.pk}?embed=1", body)
        self.assertIn("reviews/admin_preview.css", body)

    def test_change_form_iframes_activity_page(self):
        from datetime import timedelta
        from django.utils import timezone
        from activities.models import Activity

        act = Activity.objects.create(
            type="deliberation",
            status="open",
            title="后台活动预览",
            creator=self.author,
            end_at=timezone.now() + timedelta(days=1),
        )
        review = open_review(activity=act, actor=self.author)
        c = Client()
        c.force_login(self.admin)
        resp = c.get(f"/admin/reviews/review/{review.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"/#/activity/{act.pk}?embed=1", resp.content.decode())


def _grant_moderate(user):
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="reviews", codename="moderate"),
    )
    return User.objects.get(pk=user.pk)


class ReviewAdminActionsTest(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="author", password="x")
        self.mod = _grant_moderate(User.objects.create_user(username="mod", password="x"))
        self.staff = User.objects.create_user(username="staff", password="x")
        self.pending_news = News.objects.create(title="待审", author=self.author)
        self.approved_news = News.objects.create(title="已过", author=self.author)
        self.pending = open_review(news=self.pending_news, actor=self.author)
        self.approved = open_review(news=self.approved_news, actor=self.author)
        from reviews.lifecycle import APPROVE, apply
        apply(APPROVE, self.approved, self.mod)
        self.factory = RequestFactory()
        self.ma = ReviewAdmin(Review, admin.site)
        self.ma.message_user = lambda *a, **k: None

    def _req(self, user):
        req = self.factory.post("/")
        req.user = user
        return req

    def test_get_actions_hidden_without_moderate(self):
        actions = self.ma.get_actions(self._req(self.staff))
        self.assertNotIn("approve_selected", actions)
        self.assertNotIn("reject_selected", actions)
        self.assertNotIn("remove_selected", actions)

    def test_get_actions_shown_with_moderate(self):
        actions = self.ma.get_actions(self._req(self.mod))
        self.assertIn("approve_selected", actions)
        self.assertIn("reject_selected", actions)
        self.assertIn("remove_selected", actions)

    def test_approve_pending(self):
        self.ma.approve_selected(
            self._req(self.mod), Review.objects.filter(pk=self.pending.pk),
        )
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Review.STATUS_APPROVED)

    def test_reject_pending(self):
        self.ma.reject_selected(
            self._req(self.mod), Review.objects.filter(pk=self.pending.pk),
        )
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Review.STATUS_REJECTED)
        self.assertEqual(self.pending.moderation_note, "后台批量驳回")

    def test_remove_approved(self):
        self.ma.remove_selected(
            self._req(self.mod), Review.objects.filter(pk=self.approved.pk),
        )
        self.approved.refresh_from_db()
        self.assertEqual(self.approved.status, Review.STATUS_REMOVED)

    def test_ineligible_rows_skipped(self):
        self.ma.remove_selected(
            self._req(self.mod), Review.objects.filter(pk=self.pending.pk),
        )
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Review.STATUS_PENDING)

    def test_changelist_shows_three_actions(self):
        su = User.objects.create_superuser("su", "s@e.com", "x")
        c = Client()
        c.force_login(su)
        resp = c.get("/admin/reviews/review/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "通过")
        self.assertContains(resp, "驳回")
        self.assertContains(resp, "下架")
