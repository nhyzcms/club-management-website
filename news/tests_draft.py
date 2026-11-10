"""服务端草稿区（编辑页自动保存）契约测试。

设计：已发布新闻的修改进 ``draft_*`` 暂存区——公开接口不可见，直到「保存修改」上线并消费；
未发布稿件的自动保存直接写正文（稿件本体即草稿）。草稿区读 / 存 / 弃都须 ``news.manage_news``。
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from reviews.test_helpers import approve_news
from .models import News, NewsDraft


def _info(user):
    g, _ = Group.objects.get_or_create(name="信息组")
    user.groups.add(g)
    return user


class NewsDraftApiTest(TestCase):
    def setUp(self):
        self.author = _info(User.objects.create_user(username="info", password="x"))
        self.normal = User.objects.create_user(username="normal", password="x")
        self.client = APIClient()
        self.published = approve_news(News.objects.create(
            title="已发布", content="<p>旧版</p>", author=self.author, is_published=True,
        ))
        self.unpublished = News.objects.create(
            title="未发布", content="<p>初稿</p>", author=self.author, is_published=False,
        )

    def url(self, news):
        return f"/news/news/{news.pk}/draft/"

    def detail_url(self, news):
        return f"/news/news/{news.pk}/"

    # ---- 权限：草稿区读 / 写 / 弃都须 news.manage_news ----
    def test_anon_denied(self):
        resp = self.client.get(self.url(self.published))
        self.assertIn(resp.status_code, (401, 403))
        resp = self.client.post(self.url(self.published), {"content": "x"}, format="json")
        self.assertIn(resp.status_code, (401, 403))

    def test_normal_user_denied(self):
        self.client.force_authenticate(self.normal)
        self.assertIn(self.client.get(self.url(self.published)).status_code, (401, 403))
        self.assertEqual(
            self.client.post(self.url(self.published), {"content": "x"}, format="json").status_code, 403,
        )
        self.assertEqual(self.client.delete(self.url(self.published)).status_code, 403)

    # ---- 已发布：草稿区（公开页保持旧版）----
    def test_get_null_when_no_draft(self):
        self.client.force_authenticate(self.author)
        resp = self.client.get(self.url(self.published))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["draft"])

    def test_autosave_writes_draft_not_live(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post(
            self.url(self.published),
            {"title": "新版", "summary": "新摘要", "content": "<p>新版</p>"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["is_draft"])
        self.published.refresh_from_db()
        self.assertEqual(self.published.draft_title, "新版")
        self.assertEqual(self.published.draft_summary, "新摘要")
        self.assertEqual(self.published.draft_content, "<p>新版</p>")
        self.assertIsNotNone(self.published.draft_saved_at)
        # 正式区不变；匿名详情仍为旧版，且看不到草稿信息
        self.assertEqual(self.published.title, "已发布")
        self.assertEqual(self.published.content, "<p>旧版</p>")
        anon = APIClient().get(self.detail_url(self.published))
        self.assertEqual(anon.data["content"], "<p>旧版</p>")
        self.assertIsNone(anon.data["draft_saved_at"])

    def test_autosave_partial_fields_merge(self):
        self.client.force_authenticate(self.author)
        self.client.post(self.url(self.published), {"title": "T1"}, format="json")
        self.client.post(self.url(self.published), {"content": "<p>C1</p>"}, format="json")
        self.published.refresh_from_db()
        self.assertEqual(self.published.draft_title, "T1")
        self.assertEqual(self.published.draft_content, "<p>C1</p>")

    def test_autosave_sanitizes_content(self):
        self.client.force_authenticate(self.author)
        self.client.post(
            self.url(self.published), {"content": "<p>ok</p><script>alert(1)</script>"}, format="json",
        )
        self.published.refresh_from_db()
        self.assertNotIn("<script", self.published.draft_content)
        self.assertIn("ok", self.published.draft_content)

    def test_get_returns_saved_draft(self):
        self.client.force_authenticate(self.author)
        self.client.post(
            self.url(self.published), {"title": "草稿题", "content": "<p>草稿文</p>"}, format="json",
        )
        resp = self.client.get(self.url(self.published))
        self.assertEqual(resp.data["draft"]["title"], "草稿题")
        self.assertEqual(resp.data["draft"]["content"], "<p>草稿文</p>")
        self.assertIsNotNone(resp.data["draft"]["saved_at"])

    def test_discard_clears_draft(self):
        self.client.force_authenticate(self.author)
        self.client.post(
            self.url(self.published), {"title": "草稿题", "content": "<p>草稿文</p>"}, format="json",
        )
        resp = self.client.delete(self.url(self.published))
        self.assertEqual(resp.status_code, 200)
        self.published.refresh_from_db()
        self.assertIsNone(self.published.draft_saved_at)
        self.assertEqual(self.published.draft_content, "")
        self.assertIsNone(self.client.get(self.url(self.published)).data["draft"])
        # 正式区不动
        self.assertEqual(self.published.content, "<p>旧版</p>")

    def test_detail_draft_saved_at_editor_only(self):
        NewsDraft.objects.create(
            news=self.published, content="<p>草稿</p>", saved_at=timezone.now(),
        )
        anon = APIClient().get(self.detail_url(self.published))
        self.assertIsNone(anon.data["draft_saved_at"])
        self.client.force_authenticate(self.normal)
        self.assertIsNone(self.client.get(self.detail_url(self.published)).data["draft_saved_at"])
        self.client.force_authenticate(self.author)
        self.assertIsNotNone(self.client.get(self.detail_url(self.published)).data["draft_saved_at"])

    def test_list_exposes_draft_saved_at_editor_only(self):
        # 「我的稿件」列表要能标出「有未发布修改」；权限门与详情一致（匿名 / 普通用户恒 null）
        NewsDraft.objects.create(
            news=self.published, content="<p>草稿</p>", saved_at=timezone.now(),
        )
        anon = APIClient().get("/news/news/")
        items = anon.data.get("results", anon.data)
        item = next(i for i in items if i["id"] == self.published.pk)
        self.assertIsNone(item["draft_saved_at"])
        self.client.force_authenticate(self.author)
        resp = self.client.get("/news/news/")
        items = resp.data.get("results", resp.data)
        item = next(i for i in items if i["id"] == self.published.pk)
        self.assertIsNotNone(item["draft_saved_at"])

    # ---- 未发布：自动保存直接写正文（稿件本体即草稿）----
    def test_autosave_unpublished_writes_live(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post(self.url(self.unpublished), {"title": "改题", "content": "<p>改文</p>"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_draft"])
        self.unpublished.refresh_from_db()
        self.assertEqual(self.unpublished.title, "改题")
        self.assertEqual(self.unpublished.content, "<p>改文</p>")
        self.assertFalse(self.unpublished.is_published)
        self.assertIsNone(self.unpublished.draft_saved_at)
        # 未发布时 GET 恒 null（草稿区只服务「已发布稿件的待发布修改」）
        self.assertIsNone(self.client.get(self.url(self.unpublished)).data["draft"])

    def test_autosave_unpublished_blank_title_kept(self):
        self.client.force_authenticate(self.author)
        self.client.post(self.url(self.unpublished), {"title": "   ", "content": "<p>改文</p>"}, format="json")
        self.unpublished.refresh_from_db()
        self.assertEqual(self.unpublished.title, "未发布")
        self.assertEqual(self.unpublished.content, "<p>改文</p>")

    # ---- 「保存修改」消费草稿 ----
    def test_publish_update_consumes_draft(self):
        self.client.force_authenticate(self.author)
        self.client.post(
            self.url(self.published), {"title": "草稿题", "content": "<p>草稿文</p>"}, format="json",
        )
        resp = self.client.patch(
            self.detail_url(self.published),
            {"title": "上线题", "summary": "", "content": "<p>上线文</p>"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.published.refresh_from_db()
        self.assertEqual(self.published.title, "上线题")
        self.assertEqual(self.published.content, "<p>上线文</p>")
        self.assertIsNone(self.published.draft_saved_at)
        self.assertEqual(self.published.draft_content, "")

    def test_meta_only_update_keeps_draft(self):
        self.client.force_authenticate(self.author)
        self.client.post(self.url(self.published), {"content": "<p>草稿文</p>"}, format="json")
        resp = self.client.patch(self.detail_url(self.published), {"featured": True}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.published.refresh_from_db()
        self.assertIsNotNone(self.published.draft_saved_at)
        self.assertEqual(self.published.draft_content, "<p>草稿文</p>")

    # ---- 校验 ----
    def test_autosave_title_too_long_rejected(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post(self.url(self.published), {"title": "x" * 201}, format="json")
        self.assertEqual(resp.status_code, 400)
