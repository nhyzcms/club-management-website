"""Django admin 新闻批量归档。"""
from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.test import RequestFactory, TestCase

from .admin import NewsAdmin
from .models import News


class NewsAdminArchiveTest(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="author", password="x")
        self.staff = User.objects.create_user(username="staff", password="x")
        self.staff.user_permissions.add(
            Permission.objects.get(content_type__app_label="news", codename="manage_news"),
        )
        self.staff = User.objects.get(pk=self.staff.pk)
        self.published = News.objects.create(
            title="已发布", author=self.author, is_published=True,
        )
        self.draft = News.objects.create(
            title="草稿", author=self.author, is_published=False,
        )
        self.factory = RequestFactory()
        self.ma = NewsAdmin(News, admin.site)
        self.ma.message_user = lambda *a, **k: None

    def _req(self, user):
        req = self.factory.post("/")
        req.user = user
        return req

    def test_unpublishes_published_and_skips_draft(self):
        qs = News.objects.filter(pk__in=[self.published.pk, self.draft.pk])
        self.ma.archive_selected(self._req(self.staff), qs)
        self.published.refresh_from_db()
        self.draft.refresh_from_db()
        self.assertFalse(self.published.is_published)
        self.assertFalse(self.draft.is_published)

    def test_without_change_perm_is_noop(self):
        self.ma.archive_selected(
            self._req(self.author),
            News.objects.filter(pk=self.published.pk),
        )
        self.published.refresh_from_db()
        self.assertTrue(self.published.is_published)

    def test_changelist_shows_archive_action(self):
        from django.test import Client
        su = User.objects.create_superuser("su", "s@e.com", "x")
        c = Client()
        c.force_login(su)
        resp = c.get("/admin/news/news/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "归档")


class NewsAdminSanitizeTest(TestCase):
    """L-9 回归：admin 写路径也过 sanitize_html。"""

    def setUp(self):
        self.author = User.objects.create_user(username="admin_author", password="x")
        self.staff = User.objects.create_user(username="admin_staff", password="x")
        self.staff.user_permissions.add(
            Permission.objects.get(content_type__app_label="news", codename="manage_news"),
        )
        self.staff = User.objects.get(pk=self.staff.pk)
        self.factory = RequestFactory()
        self.ma = NewsAdmin(News, admin.site)

    def test_admin_save_sanitizes_content(self):
        obj = News(
            title="x", author=self.author,
            content='<p>ok</p><script>alert(1)</script><img src=x onerror="alert(2)">',
        )
        req = self.factory.post("/")
        req.user = self.staff
        self.ma.save_model(req, obj, form=None, change=False)
        obj.refresh_from_db()
        self.assertIn("ok", obj.content)
        self.assertNotIn("<script", obj.content)
        self.assertNotIn("onerror", obj.content)
