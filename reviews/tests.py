"""统一审核轴核 + 新闻接入（#70 / T01）。

Seams（HTTP 公共接口，不测内部结构）：
- ``POST/GET /news/news/`` 与详情：创建后的公开可见性、作者/审核员预览
- ``GET/POST /reviews/reviews/``：统一审核队列与通过/驳回/下架
- ``GET /auth/me/``：``can_force_publish`` / ``can_review_content`` 能力投影
"""

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from common.models import SiteSettings
from reviews.models import Review


def _grant(user, app_label, *codenames):
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return user


def _author():
    user = User.objects.create_user(username="author", password="x")
    return _grant(user, "news", "manage_news")


def _moderator():
    user = User.objects.create_user(username="mod", password="x")
    return _grant(user, "reviews", "moderate")


def _publisher():
    user = User.objects.create_user(username="pub", password="x")
    _grant(user, "news", "manage_news")
    return _grant(user, "reviews", "force_publish")


def _ids(resp):
    return [row["id"] for row in resp.data["results"]]


class NewsSubmitEntersPendingTest(TestCase):
    """非免审发布者提交新闻 → 待审；公开列表/详情读不到。"""

    def setUp(self):
        self.author = _author()
        self.client = APIClient()
        self.client.force_authenticate(self.author)

    def test_create_without_force_publish_is_hidden_from_public_list(self):
        resp = self.client.post("/news/news/", {"title": "待审稿"}, format="json")
        self.assertEqual(resp.status_code, 201)
        news_id = resp.data["id"]
        self.assertEqual(resp.data.get("review_status"), "pending")

        public = APIClient()
        listing = public.get("/news/news/")
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn(news_id, _ids(listing))

        detail = public.get(f"/news/news/{news_id}/")
        self.assertEqual(detail.status_code, 404)


class ContentReviewDisabledSkipsQueueTest(TestCase):
    """content_review_enabled=False → 新建直接通过，无需 force_publish。"""

    def setUp(self):
        super().setUp()
        cache.clear()
        obj, _ = SiteSettings.objects.get_or_create(pk=1)
        obj.content_review_enabled = False
        obj.save()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_create_without_force_publish_is_approved(self):
        client = APIClient()
        client.force_authenticate(_author())
        resp = client.post("/news/news/", {"title": "免审稿"}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["review_status"], "approved")
        news_id = resp.data["id"]

        public = APIClient()
        listing = public.get("/news/news/")
        self.assertIn(news_id, _ids(listing))
        self.assertEqual(public.get(f"/news/news/{news_id}/").status_code, 200)


class ForcePublishSkipsReviewTest(TestCase):
    """持 force_publish 者新建新闻直接公开。"""

    def test_create_with_force_publish_is_public(self):
        client = APIClient()
        client.force_authenticate(_publisher())
        resp = client.post("/news/news/", {"title": "直发稿"}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["review_status"], "approved")
        news_id = resp.data["id"]

        public = APIClient()
        listing = public.get("/news/news/")
        self.assertIn(news_id, _ids(listing))
        self.assertEqual(public.get(f"/news/news/{news_id}/").status_code, 200)


class CreatorAndModeratorPreviewTest(TestCase):
    """待审新闻对作者/持审核权限者可见，对其他登录用户隐藏。"""

    def setUp(self):
        self.author = _author()
        self.mod = _moderator()
        self.other = User.objects.create_user(username="other", password="x")
        writer = APIClient()
        writer.force_authenticate(self.author)
        created = writer.post("/news/news/", {"title": "预览稿"}, format="json")
        self.news_id = created.data["id"]

    def test_author_can_retrieve_pending(self):
        client = APIClient()
        client.force_authenticate(self.author)
        resp = client.get(f"/news/news/{self.news_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["review_status"], "pending")

    def test_moderator_can_retrieve_pending(self):
        client = APIClient()
        client.force_authenticate(self.mod)
        self.assertEqual(client.get(f"/news/news/{self.news_id}/").status_code, 200)

    def test_other_user_cannot_retrieve_pending(self):
        client = APIClient()
        client.force_authenticate(self.other)
        self.assertEqual(client.get(f"/news/news/{self.news_id}/").status_code, 404)


class ReviewQueueActionsTest(TestCase):
    """审核员从统一队列对新闻 通过 / 驳回 / 下架。"""

    def setUp(self):
        self.author = _author()
        self.mod = _moderator()
        writer = APIClient()
        writer.force_authenticate(self.author)
        created = writer.post("/news/news/", {"title": "队列稿"}, format="json")
        self.news_id = created.data["id"]
        self.review_id = Review.objects.get(news_id=self.news_id).pk
        self.client = APIClient()
        self.client.force_authenticate(self.mod)

    def test_queue_lists_pending_news(self):
        resp = self.client.get("/reviews/reviews/?status=pending")
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.review_id)
        self.assertEqual(rows[0]["target_type"], "news")
        self.assertEqual(rows[0]["target_id"], self.news_id)
        self.assertEqual(rows[0]["title"], "队列稿")
        self.assertEqual(rows[0]["status"], "pending")

    def test_stranger_cannot_list_queue(self):
        client = APIClient()
        client.force_authenticate(self.author)
        self.assertEqual(client.get("/reviews/reviews/").status_code, 403)

    def test_approve_makes_news_public(self):
        resp = self.client.post(f"/reviews/reviews/{self.review_id}/approve/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "approved")

        public = APIClient()
        self.assertIn(self.news_id, _ids(public.get("/news/news/")))
        self.assertEqual(public.get(f"/news/news/{self.news_id}/").status_code, 200)

    def test_reject_with_comment_keeps_news_hidden(self):
        resp = self.client.post(
            f"/reviews/reviews/{self.review_id}/reject/",
            {"comment": "标题不准确"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "rejected")
        self.assertEqual(resp.data["comment"], "标题不准确")

        public = APIClient()
        self.assertNotIn(self.news_id, _ids(public.get("/news/news/")))

    def test_reject_without_comment_is_400(self):
        resp = self.client.post(f"/reviews/reviews/{self.review_id}/reject/", {}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_remove_hides_approved_news(self):
        self.client.post(f"/reviews/reviews/{self.review_id}/approve/")
        resp = self.client.post(f"/reviews/reviews/{self.review_id}/remove/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "removed")

        public = APIClient()
        self.assertNotIn(self.news_id, _ids(public.get("/news/news/")))

    def test_author_preview_includes_reject_comment(self):
        self.client.post(
            f"/reviews/reviews/{self.review_id}/reject/",
            {"comment": "标题不准确"},
            format="json",
        )
        author = APIClient()
        author.force_authenticate(self.author)
        resp = author.get(f"/news/news/{self.news_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["review_status"], "rejected")
        self.assertEqual(resp.data["review_comment"], "标题不准确")

    def test_public_approved_detail_hides_review_comment(self):
        self.client.post(
            f"/reviews/reviews/{self.review_id}/approve/",
            {"comment": "内部备注"},
            format="json",
        )
        public = APIClient()
        resp = public.get(f"/news/news/{self.news_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["review_status"], "approved")
        self.assertEqual(resp.data["review_comment"], "")


class NewsMineListTest(TestCase):
    """作者预览列表含待审稿；公开列表不含。"""

    def test_mine_includes_pending_and_public_list_does_not(self):
        author = _author()
        client = APIClient()
        client.force_authenticate(author)
        created = client.post("/news/news/", {"title": "我的待审稿"}, format="json")
        news_id = created.data["id"]
        mine = client.get("/news/news/mine/")
        self.assertEqual(mine.status_code, 200)
        self.assertIn(news_id, _ids(mine))
        self.assertNotIn(news_id, _ids(APIClient().get("/news/news/")))

    def test_anonymous_mine_is_denied(self):
        self.assertIn(APIClient().get("/news/news/mine/").status_code, (401, 403))


class ReviewCapabilitiesTest(TestCase):
    """能力布尔由 has_perm 派生，不查组名。"""

    def test_me_exposes_review_capabilities(self):
        user = _moderator()
        _grant(user, "reviews", "force_publish")
        client = APIClient()
        client.force_login(user)
        resp = client.get("/auth/me/")
        self.assertEqual(resp.status_code, 200)
        perms = resp.json()["user"]["permissions"]
        self.assertTrue(perms["can_review_content"])
        self.assertTrue(perms["can_force_publish"])

    def test_plain_user_capabilities_false(self):
        user = User.objects.create_user(username="plain", password="x")
        client = APIClient()
        client.force_login(user)
        perms = client.get("/auth/me/").json()["user"]["permissions"]
        self.assertFalse(perms["can_review_content"])
        self.assertFalse(perms["can_force_publish"])


class SelfReviewDeniedTest(TestCase):
    """L-10 回归：同一账号不能批准自己创建的内容。"""

    def setUp(self):
        self.author = _grant(_author(), "reviews", "moderate")
        client = APIClient()
        client.force_authenticate(self.author)
        created = client.post("/news/news/", {"title": "自审稿"}, format="json")
        self.review_id = Review.objects.get(news_id=created.data["id"]).pk
        self.client = APIClient()
        self.client.force_authenticate(self.author)

    def test_cannot_approve_own_content(self):
        resp = self.client.post(f"/reviews/reviews/{self.review_id}/approve/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("自己", resp.data["detail"])
        self.assertEqual(Review.objects.get(pk=self.review_id).status, Review.STATUS_PENDING)

    def test_force_publisher_can_self_approve(self):
        _grant(self.author, "reviews", "force_publish")
        author = User.objects.get(pk=self.author.pk)
        self.client.force_authenticate(author)
        resp = self.client.post(f"/reviews/reviews/{self.review_id}/approve/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], Review.STATUS_APPROVED)
