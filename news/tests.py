import os
from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, RequestFactory
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import MemberIdentity
from activities.models import Activity
from tasks.models import Task

from reviews.test_helpers import approve_news
from .models import News
from .feed import build_feed


def _info(user):
    g, _ = Group.objects.get_or_create(name="信息组")
    user.groups.add(g)
    return user


class NewsContentSanitizeTest(TestCase):
    """NewsDetailSerializer.validate_content 仍经 sanitize_html（与 common 共享净化）。"""

    def test_validate_content_strips_script(self):
        from news.serializers import NewsDetailSerializer
        out = NewsDetailSerializer().validate_content("<p>ok</p><script>alert(1)</script>")
        self.assertNotIn("<script", out)
        self.assertIn("ok", out)


class NewsPermissionTest(TestCase):
    def setUp(self):
        self.author = _info(User.objects.create_user(username="info", password="x"))
        self.normal = User.objects.create_user(username="normal", password="x")
        self.client = APIClient()
        self.news = approve_news(News.objects.create(title="t", author=self.author, is_published=True))

    def test_anon_can_read_list(self):
        self.assertEqual(self.client.get("/news/news/").status_code, 200)

    def test_info_group_can_create(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post("/news/news/", {"title": "new"}, format="json")
        self.assertEqual(resp.status_code, 201)

    def test_normal_user_cannot_create(self):
        self.client.force_authenticate(self.normal)
        resp = self.client.post("/news/news/", {"title": "new"}, format="json")
        self.assertEqual(resp.status_code, 403)


class NewsReaderCountTest(TestCase):
    """阅读量去重（登录按 user / 匿名按 IP）与头条（手工优先 else 最热）。"""

    def setUp(self):
        self.author = _info(User.objects.create_user(username="info", password="x"))
        self.normal = User.objects.create_user(username="normal", password="x")
        self.client = APIClient()
        self.news = approve_news(News.objects.create(title="t", author=self.author, is_published=True))

    def test_view_once_per_user(self):
        """同一登录用户多次打开详情只算一次阅读。"""
        self.client.force_authenticate(self.normal)
        for _ in range(3):
            self.client.get(f"/news/news/{self.news.pk}/")
        self.news.refresh_from_db()
        self.assertEqual(self.news.views, 1)
        self.assertEqual(self.news.view_records.count(), 1)

    def test_view_once_per_ip_anon(self):
        """同一匿名 IP 多次打开详情只算一次阅读。"""
        for _ in range(3):
            self.client.get(f"/news/news/{self.news.pk}/")
        self.news.refresh_from_db()
        self.assertEqual(self.news.views, 1)

    def test_different_users_each_count(self):
        """不同登录用户各算一次阅读。"""
        other = User.objects.create_user(username="other", password="x")
        self.client.force_authenticate(self.normal)
        self.client.get(f"/news/news/{self.news.pk}/")
        self.client.force_authenticate(other)
        self.client.get(f"/news/news/{self.news.pk}/")
        self.news.refresh_from_db()
        self.assertEqual(self.news.views, 2)

    def test_featured_manual_priority(self):
        """手工置顶（featured）优先于阅读人数最高。"""
        approve_news(News.objects.create(title="hot", author=self.author, is_published=True, views=100))
        feat = approve_news(News.objects.create(
            title="feat", author=self.author, is_published=True, views=1, featured=True
        ))
        resp = self.client.get("/news/news/featured/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], feat.id)

    def test_featured_without_manual_flag_is_null(self):
        """没有手工置顶时不再退化为「最热」——不能把普通新闻误标成头条。"""
        approve_news(News.objects.create(title="low", author=self.author, is_published=True, views=1))
        approve_news(News.objects.create(title="high", author=self.author, is_published=True, views=100))
        resp = self.client.get("/news/news/featured/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data)


class NewsOverviewTest(TestCase):
    """社团概览：成员=已分配社员编号数（名册行数），作品=已发布新闻数；匿名可读。"""

    def setUp(self):
        self.author = _info(User.objects.create_user(username="info", password="x"))
        self.normal = User.objects.create_user(username="normal", password="x")
        News.objects.create(title="published", author=self.author, is_published=True)
        News.objects.create(title="draft", author=self.author, is_published=False)
        approve_news(News.objects.get(title="published"))
        self.client = APIClient()

    def _identity(self, name, code, **kwargs):
        return MemberIdentity.objects.create(
            name=name, admit_year=2025, cohort=1, code=code, **kwargs
        )

    def test_anon_overview_counts(self):
        """匿名可读；成员=名册行数，作品=已发布新闻数（草稿不计）。"""
        self._identity("张一", "25010151")
        self._identity("张二", "25010152")
        resp = self.client.get("/news/news/overview/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["members"], 2)  # 两条编号
        self.assertEqual(resp.data["works"], 1)    # 仅 1 条已发布

    def test_identity_without_account_counted(self):
        """分配了编号但没注册账号（user=None）也计入；有账号但无名册行不计。"""
        self._identity("李四", "25010161")  # 未绑定任何账号
        resp = self.client.get("/news/news/overview/")
        self.assertEqual(resp.status_code, 200)
        # 站内有 info / normal 两个活跃账号，但没有名册行 → 成员数按编号算 = 1
        self.assertEqual(resp.data["members"], 1)

    def test_no_roster_means_zero(self):
        """名册为空时成员为 0（不再退回活跃账号数）。"""
        resp = self.client.get("/news/news/overview/")
        self.assertEqual(resp.data["members"], 0)


class FeedTest(TestCase):
    """build_feed：可见性 / 排序 / 打散 / 公开投影 / limit / 空态。"""

    def setUp(self):
        self.rf = RequestFactory()
        self.author = _info(User.objects.create_user(username="info", password="x"))
        self.member = User.objects.create_user(username="member", password="x")
        self.anon = self.rf.get("/news/news/feed/")
        self.anon.user = AnonymousUser()
        self.authed = self.rf.get("/news/news/feed/")
        self.authed.user = self.member

    # ---- fixtures ----
    @staticmethod
    def _ts(days_ago):
        return timezone.now() - timedelta(days=days_ago)

    def _news(self, title, days_ago=0, **kw):
        kw.setdefault("author", self.author)
        kw.setdefault("is_published", True)
        kw["published_at"] = self._ts(days_ago)
        return approve_news(News.objects.create(title=title, **kw))

    def _activity(self, title, days_ago=0, **kw):
        # 活动已迁移至 activities app（ADR 0007）；feed 取 created_at 作时间戳。
        kw.setdefault("type", "deliberation")
        kw.setdefault("status", "open")
        kw.setdefault("creator", self.author)
        a = Activity.objects.create(title=title, **kw)
        Activity.objects.filter(pk=a.pk).update(created_at=self._ts(days_ago))  # auto_now_add 之外需 .update
        return a

    def _task(self, title, days_ago=0, **kw):
        kw.setdefault("creator", self.member)
        kw.setdefault("status", "in_progress")
        t = Task.objects.create(title=title, **kw)
        Task.objects.filter(pk=t.pk).update(updated_at=self._ts(days_ago))  # auto_now 字段需 .update 绕过
        return t

    @staticmethod
    def _types(items):
        return [i["type"] for i in items]

    # ---- cases ----
    def test_featured_excluded_from_items(self):
        feat = self._news("feat", days_ago=1, featured=True)
        other = self._news("other", days_ago=0)
        data = build_feed(request=self.anon)
        self.assertEqual(data["featured"]["id"], feat.pk)
        ids = [i["id"] for i in data["items"]]
        self.assertIn(other.pk, ids)
        self.assertNotIn(feat.pk, ids)

    def test_no_manual_featured_means_no_headline(self):
        """没有手工置顶时头条为 None（普通新闻仍留在 items 里，但不带头条身份）。"""
        self._news("plain", days_ago=0)
        data = build_feed(request=self.anon)
        self.assertIsNone(data["featured"])
        self.assertIn("plain", [i["title"] for i in data["items"]])

    def test_ended_activities_sink_to_bottom(self):
        """已结束活动沉底；进行中的排前面，同档按发布时间倒序。"""
        self._activity("ongoing-old", days_ago=5, status="open")
        self._activity("ended-new", days_ago=0, status="closed")
        self._activity("ongoing-new", days_ago=1, status="collecting")
        titles = [i["title"] for i in build_feed(request=self.anon)["items"]]
        self.assertEqual(titles, ["ongoing-new", "ongoing-old", "ended-new"])

    def test_diversify_keeps_ended_activity_last(self):
        """三条新闻连续触发打散时，不得把沉底的已结束活动换回前排。"""
        self._news("n1", days_ago=3)
        self._news("n2", days_ago=2)
        self._news("n3", days_ago=1)
        self._activity("ended", days_ago=0, status="closed")
        titles = [i["title"] for i in build_feed(request=self.anon)["items"]]
        self.assertEqual(titles[-1], "ended")

    def test_anon_has_news_but_no_tasks(self):
        self._news("n1", days_ago=1)
        self._news("n2", days_ago=0)
        self._task("t", days_ago=0)
        data = build_feed(request=self.anon)
        self.assertNotIn("task", self._types(data["items"]))
        self.assertIn("news", self._types(data["items"]))

    def test_authed_includes_tasks(self):
        self._news("n1", days_ago=1)
        self._news("n2", days_ago=0)
        self._task("t", days_ago=0)
        data = build_feed(request=self.authed)
        self.assertIn("task", self._types(data["items"]))

    def test_ordering_desc_by_timestamp(self):
        self._news("feat", days_ago=10, featured=True)  # 头条，不参与 items
        self._news("old", days_ago=3)
        self._news("mid", days_ago=2)
        self._news("new", days_ago=1)
        data = build_feed(request=self.anon)
        self.assertEqual([i["title"] for i in data["items"]], ["new", "mid", "old"])

    def test_diversify_breaks_three_in_a_row(self):
        self._news("feat", days_ago=10, featured=True)  # 头条锚点，不参与 items（否则最热新闻会被选走，打散无从验证）
        self._activity("act", days_ago=4)                # 最旧
        self._news("old", days_ago=3)
        self._news("mid", days_ago=2)
        self._news("new", days_ago=1)                    # 排序后 [new,mid,old,act] → 连续 3 新闻需打散
        types = self._types(build_feed(request=self.anon)["items"])
        windows = [types[i:i + 3] for i in range(len(types) - 2)]
        self.assertNotIn(["news", "news", "news"], windows)
        self.assertEqual(set(types), {"news", "activity"})

    def test_activity_projection_excludes_internal_fields(self):
        self._activity("act", days_ago=0)
        act = next(i for i in build_feed(request=self.anon)["items"] if i["type"] == "activity")
        for forbidden in ("budget", "vote_summary", "reject_reason", "contact", "creator", "description", "body", "options"):
            self.assertNotIn(forbidden, act)
        self.assertIn(act["activity_type"], ("deliberation", "collection", "exhibition"))
        self.assertIn("status", act)

    def test_exhibition_activity_in_feed(self):
        """展示活动须进入 feed 且 activity_type=exhibition——前端 ActivityCard 据此查
        ACTIVITY_META 渲染；后端若漏投或类型串错，卡片即崩（回归 #49）。"""
        self._activity("影展", days_ago=0, type="exhibition", status="open")
        items = build_feed(request=self.anon)["items"]
        ex = next(
            (i for i in items if i["type"] == "activity" and i["activity_type"] == "exhibition"),
            None,
        )
        self.assertIsNotNone(ex, "展示活动应出现在 feed items 中")
        # 公开投影与其它活动同形：不泄露内部字段（展品/正文/选项等）
        for forbidden in ("budget", "body", "options", "exhibits", "creator"):
            self.assertNotIn(forbidden, ex)

    def test_guest_feed_hides_members_only_surveys(self):
        """访客不可见仅成员调研；公开调研可见；众议标题泄漏保持原样。"""
        self._activity("public-survey", days_ago=0, type="survey", status="open", audience="public")
        self._activity("members-survey", days_ago=0, type="survey", status="open", audience="members")
        self._activity("delib", days_ago=0, type="deliberation", status="open")
        guest_titles = {i["title"] for i in build_feed(request=self.anon)["items"] if i["type"] == "activity"}
        self.assertIn("public-survey", guest_titles)
        self.assertNotIn("members-survey", guest_titles)
        self.assertIn("delib", guest_titles)
        member_titles = {i["title"] for i in build_feed(request=self.authed)["items"] if i["type"] == "activity"}
        self.assertIn("members-survey", member_titles)
        self.assertIn("public-survey", member_titles)

    def test_limit_truncates(self):
        for i in range(10):
            self._news(f"n{i}", days_ago=i)
        data = build_feed(request=self.anon, limit=4)
        self.assertLessEqual(len(data["items"]), 4)

    def test_empty_when_no_content(self):
        data = build_feed(request=self.anon)
        self.assertIsNone(data["featured"])
        self.assertEqual(data["items"], [])


class FeedEndpointTest(TestCase):
    """端点 /news/news/feed/：匿名可读、不含任务；登录含任务。"""

    def setUp(self):
        self.author = _info(User.objects.create_user(username="info", password="x"))
        self.member = User.objects.create_user(username="member", password="x")
        approve_news(News.objects.create(title="n1", author=self.author, is_published=True))
        Activity.objects.create(type="deliberation", status="open", title="a1", creator=self.author)
        Task.objects.create(title="t1", creator=self.member, status="in_progress")
        self.client = APIClient()

    def test_anon_ok_without_tasks(self):
        resp = self.client.get("/news/news/feed/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("featured", resp.data)
        self.assertNotIn("task", {i["type"] for i in resp.data["items"]})

    def test_authed_includes_tasks(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get("/news/news/feed/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("task", {i["type"] for i in resp.data["items"]})

    def test_limit_query_param(self):
        self.client.force_authenticate(self.member)
        resp = self.client.get("/news/news/feed/?limit=1")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.data["items"]), 1)


class NewsRelatedTest(TestCase):
    """详情 related：按发布时间最新 3 条公开稿，不含自身。"""

    def setUp(self):
        self.author = _info(User.objects.create_user(username="info", password="x"))
        self.client = APIClient()

    def _news(self, title, days_ago=0):
        n = approve_news(News.objects.create(
            title=title, author=self.author, is_published=True,
        ))
        News.objects.filter(pk=n.pk).update(
            published_at=timezone.now() - timedelta(days=days_ago),
        )
        return n

    def test_related_is_latest_public_excluding_self(self):
        current = self._news("current", days_ago=0)
        for i in range(1, 5):
            self._news(f"n{i}", days_ago=i)
        resp = self.client.get(f"/news/news/{current.pk}/")
        self.assertEqual(resp.status_code, 200)
        titles = [r["title"] for r in resp.data["related"]]
        self.assertEqual(titles, ["n1", "n2", "n3"])
        self.assertNotIn("current", titles)
        self.assertNotIn("n4", titles)
        self.assertNotIn("category", resp.data)


class NewsAuthorEmailVisibilityTest(TestCase):
    """公开读接口不得随内容泄露作者 email（字段级越权回归）。

    匿名 / 非本人登录视角下，列表与详情中的 author 均不含 email；作者本人经
    mine 读取自己的新闻时 email 保留（与 accounts.visibility 的
    can_see_private = owner 对齐）。
    """

    def setUp(self):
        self.author = _info(
            User.objects.create_user(username="info_email", password="x", email="author@example.com")
        )
        self.other = User.objects.create_user(username="other_email", password="x", email="other@example.com")
        self.client = APIClient()
        self.news = approve_news(News.objects.create(title="t", author=self.author, is_published=True))

    def test_anon_list_hides_author_email(self):
        resp = self.client.get("/news/news/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("email", resp.data["results"][0]["author"])

    def test_anon_detail_hides_author_email(self):
        resp = self.client.get(f"/news/news/{self.news.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("email", resp.data["author"])

    def test_authenticated_other_hides_author_email(self):
        self.client.force_authenticate(self.other)
        resp = self.client.get("/news/news/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("email", resp.data["results"][0]["author"])

    def test_author_mine_keeps_own_email(self):
        self.client.force_authenticate(self.author)
        resp = self.client.get("/news/news/mine/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["results"][0]["author"]["email"], "author@example.com")


class NewsCoverThumbnailTest(TestCase):
    """封面上传：5MB 上限、缩略图生成 / 回退 / 换封面清理。"""

    def setUp(self):
        self.author = _info(User.objects.create_user(username="reporter", password="x"))
        self.client = APIClient()
        self.client.force_authenticate(self.author)

    @staticmethod
    def _image_file(width=1600, height=900, fmt="JPEG", name=None):
        buf = BytesIO()
        Image.new("RGB", (width, height), (180, 40, 40)).save(buf, format=fmt)
        ext = "jpg" if fmt == "JPEG" else fmt.lower()
        ct = "image/jpeg" if fmt == "JPEG" else f"image/{ext}"
        return SimpleUploadedFile(name or f"cover.{ext}", buf.getvalue(), content_type=ct)

    def _post_news(self, cover=None, title="带封面新闻"):
        data = {"title": title, "is_published": True}
        if cover is not None:
            data["cover_image"] = cover
        return self.client.post("/news/news/", data, format="multipart")

    def test_upload_generates_thumbnail(self):
        """上传 1600x900 封面 → 缩略图 800x450（宽 ≤800、保持比例、JPEG）。"""
        resp = self._post_news(self._image_file())
        self.assertEqual(resp.status_code, 201)
        news = News.objects.get(title="带封面新闻")
        self.assertTrue(news.cover_thumbnail)
        with Image.open(news.cover_thumbnail.path) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual((img.width, img.height), (800, 450))

    def test_small_image_kept_size(self):
        """小图（≤800 宽）缩略图不放大。"""
        self._post_news(self._image_file(400, 300))
        news = News.objects.get(title="带封面新闻")
        with Image.open(news.cover_thumbnail.path) as img:
            self.assertEqual((img.width, img.height), (400, 300))

    def test_list_exposes_thumbnail_url(self):
        """列表返回 cover_thumbnail_url（缩略图 /thumbs/ 路径）。"""
        self._post_news(self._image_file())
        approve_news(News.objects.get(title="带封面新闻"))
        resp = self.client.get("/news/news/")
        item = next(n for n in resp.data["results"] if n["title"] == "带封面新闻")
        self.assertIn("/thumbs/", item["cover_thumbnail_url"])

    def test_thumbnail_url_falls_back_to_cover(self):
        """旧数据无缩略图 → cover_thumbnail_url 回退原图 URL。"""
        news = approve_news(News.objects.create(title="旧新闻", author=self.author, is_published=True))
        news.cover_image = self._image_file(300, 200, name="old.jpg")
        news.save()
        resp = self.client.get(f"/news/news/{news.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["cover_thumbnail_url"], resp.data["cover_image_url"])

    @staticmethod
    def _noise_jpeg(width=2400, height=2400, quality=95):
        """随机噪点 JPEG（不可压缩 → 体积大）；2400x2400 约 6.4MB。"""
        img = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
        buf = BytesIO()
        img.save(buf, "JPEG", quality=quality)
        return buf.getvalue()

    def test_cover_over_5mb_rejected(self):
        """封面 >5MB（有效图）→ 400 拒绝。"""
        payload = self._noise_jpeg()
        self.assertGreater(len(payload), 5 * 1024 * 1024)  # 前提：确实超限
        big = SimpleUploadedFile("big.jpg", payload, content_type="image/jpeg")
        resp = self._post_news(big)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("5MB", str(resp.data))

    def test_replace_cover_regenerates_and_cleans(self):
        """换封面 → 缩略图重建、旧缩略图文件删除。"""
        self._post_news(self._image_file())
        news = News.objects.get(title="带封面新闻")
        old_thumb_name = news.cover_thumbnail.name
        storage = news.cover_thumbnail.storage
        self.assertTrue(storage.exists(old_thumb_name))
        resp = self.client.patch(
            f"/news/news/{news.pk}/",
            {"cover_image": self._image_file(600, 600, name="new.jpg")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200)
        news.refresh_from_db()
        self.assertNotEqual(news.cover_thumbnail.name, old_thumb_name)
        self.assertFalse(storage.exists(old_thumb_name))
        with Image.open(news.cover_thumbnail.path) as img:
            self.assertEqual((img.width, img.height), (600, 600))


class NewsCoverPreuploadTest(TestCase):
    """封面「选完即传」：upload_cover 预上传 + cover_image_ref 挂载 / 替换 / 清除 / 引用校验。"""

    def setUp(self):
        self.author = _info(User.objects.create_user(username="reporter_pre", password="x"))
        self.client = APIClient()
        self.client.force_authenticate(self.author)

    @staticmethod
    def _image_file(width=1600, height=900, fmt="JPEG", name=None):
        buf = BytesIO()
        Image.new("RGB", (width, height), (30, 120, 60)).save(buf, format=fmt)
        ext = "jpg" if fmt == "JPEG" else fmt.lower()
        ct = "image/jpeg" if fmt == "JPEG" else f"image/{ext}"
        return SimpleUploadedFile(name or f"cover.{ext}", buf.getvalue(), content_type=ct)

    @staticmethod
    def _ref_path(url):
        return url.split("/media/", 1)[1]

    def _upload(self, f=None):
        return self.client.post(
            "/news/news/upload_cover/", {"image": f or self._image_file()}, format="multipart",
        )

    def test_upload_cover_saves_file_and_returns_url(self):
        """预上传：文件落 news_covers/，返回可直接引用的 URL。"""
        resp = self._upload()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("/media/news_covers/", resp.data["url"])
        self.assertTrue(default_storage.exists(self._ref_path(resp.data["url"])))

    def test_upload_cover_accepts_webp(self):
        """WebP（手机常见格式）可预上传。"""
        resp = self._upload(self._image_file(fmt="WEBP"))
        self.assertEqual(resp.status_code, 200)

    def test_upload_cover_rejects_big_and_bad_type(self):
        big = SimpleUploadedFile("big.jpg", os.urandom(5 * 1024 * 1024 + 1), content_type="image/jpeg")
        self.assertEqual(self._upload(big).status_code, 400)
        bad = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        self.assertEqual(self._upload(bad).status_code, 400)

    def test_upload_cover_requires_permission(self):
        """无 news.manage_news → 403（与正文图上传同门）。"""
        self.client.force_authenticate(User.objects.create_user(username="nobody_pre", password="x"))
        self.assertEqual(self._upload().status_code, 403)

    def test_create_with_ref_attaches_and_generates_thumbnail(self):
        """新建携带引用：封面挂载 + 缩略图生成（800x450）。"""
        url = self._upload().data["url"]
        resp = self.client.post(
            "/news/news/",
            {"title": "预上传封面", "is_published": True, "cover_image_ref": url},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        news = News.objects.get(title="预上传封面")
        self.assertEqual(news.cover_image.name, self._ref_path(url))
        self.assertTrue(news.cover_thumbnail)
        with Image.open(news.cover_thumbnail.path) as img:
            self.assertEqual((img.width, img.height), (800, 450))

    def test_update_ref_replaces_and_cleans_old(self):
        """换引用：旧封面 / 旧缩略图文件删除、缩略图按新图重建。"""
        url1 = self._upload().data["url"]
        resp = self.client.post("/news/news/", {"title": "换封面", "cover_image_ref": url1}, format="multipart")
        news = News.objects.get(pk=resp.data["id"])
        old_cover, old_thumb = news.cover_image.name, news.cover_thumbnail.name
        storage = news.cover_image.storage
        url2 = self._upload(self._image_file(600, 600, name="second.jpg")).data["url"]
        resp2 = self.client.patch(f"/news/news/{news.pk}/", {"cover_image_ref": url2}, format="multipart")
        self.assertEqual(resp2.status_code, 200)
        news.refresh_from_db()
        self.assertEqual(news.cover_image.name, self._ref_path(url2))
        self.assertFalse(storage.exists(old_cover))
        self.assertFalse(storage.exists(old_thumb))
        with Image.open(news.cover_thumbnail.path) as img:
            self.assertEqual((img.width, img.height), (600, 600))

    def test_clear_ref_removes_cover_and_thumbnail(self):
        """空串引用 = 清除封面：文件与缩略图一并删除。"""
        url = self._upload().data["url"]
        resp = self.client.post("/news/news/", {"title": "清除封面", "cover_image_ref": url}, format="multipart")
        news = News.objects.get(pk=resp.data["id"])
        cover_name, thumb_name = news.cover_image.name, news.cover_thumbnail.name
        storage = news.cover_image.storage
        resp2 = self.client.patch(f"/news/news/{news.pk}/", {"cover_image_ref": ""}, format="multipart")
        self.assertEqual(resp2.status_code, 200)
        news.refresh_from_db()
        self.assertFalse(news.cover_image)
        self.assertFalse(news.cover_thumbnail)
        self.assertFalse(storage.exists(cover_name))
        self.assertFalse(storage.exists(thumb_name))

    def test_ref_validation_rejects_invalid(self):
        """引用校验：非法路径 / 穿越 / 缩略图 / 不存在 → 400。"""
        bad_refs = [
            "news_covers/../secret.jpg",
            "news_covers/thumbs/x.jpg",
            "other_place/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg",
            "news_covers/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg",
            "/media/news_covers/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg",
        ]
        for i, ref in enumerate(bad_refs):
            resp = self.client.post(
                "/news/news/", {"title": f"bad-{i}", "cover_image_ref": ref}, format="multipart",
            )
            self.assertEqual(resp.status_code, 400, msg=ref)

    def test_ref_rejects_other_news_cover(self):
        """同一文件不允许挂到第二条新闻（防替换时误删他人封面）。"""
        url = self._upload().data["url"]
        resp1 = self.client.post("/news/news/", {"title": "先占", "cover_image_ref": url}, format="multipart")
        self.assertEqual(resp1.status_code, 201)
        resp2 = self.client.post("/news/news/", {"title": "蹭图", "cover_image_ref": url}, format="multipart")
        self.assertEqual(resp2.status_code, 400)

    def test_create_with_both_cover_fields_rejected(self):
        """cover_image 与 cover_image_ref 不可同时携带。"""
        url = self._upload().data["url"]
        resp = self.client.post(
            "/news/news/",
            {"title": "双传", "cover_image": self._image_file(name="f.jpg"), "cover_image_ref": url},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)
