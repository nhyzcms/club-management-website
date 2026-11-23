"""legacy 只读版测试：可见性、只读约束、安全响应头、富文本清洗。

这些断言全部走 Django test client，不依赖浏览器、不进 e2e——
Playwright 没有 IE 引擎，旧浏览器只能用「给定 UA → 断言 HTML 片段」的方式验收。
"""

import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from about.models import AboutBlock, AboutPage
from common.throttles import PublicReadThrottle
from news.models import News
from reviews.lifecycle import open_review

from .queries import public_news

#: 用例共用 127.0.0.1 这一个 IP，真实阈值（300/min）会让彼此干扰；限流本身另有专测。
_TEST_RATE = "100000/min"
_original_rate = None


def setUpModule():
    global _original_rate
    _original_rate = PublicReadThrottle.RATE
    PublicReadThrottle.RATE = _TEST_RATE


def tearDownModule():
    PublicReadThrottle.RATE = _original_rate


IE8_UA = "Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1; Trident/4.0)"
IE6_UA = "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; SV1)"


class LegacyTestCase(TestCase):
    def setUp(self):
        self.author = User.objects.create_user("legacy_author", password="x")
        now = timezone.now()
        self.approved = News.objects.create(
            title="已过审的新闻标题",
            summary="已过审的摘要",
            content="<p>正文</p>",
            author=self.author,
            is_published=True,
            published_at=now - timedelta(hours=1),
        )
        open_review(news=self.approved, actor=self.author, force_publish=True)
        self.pending = News.objects.create(
            title="待审核的新闻标题",
            author=self.author,
            is_published=True,
            published_at=now,
        )
        open_review(news=self.pending, actor=self.author)
        self.draft = News.objects.create(
            title="未发布的草稿标题",
            author=self.author,
            is_published=False,
            published_at=now,
        )
        open_review(news=self.draft, actor=self.author, force_publish=True)


class VisibilityTest(LegacyTestCase):
    def test_home_lists_only_approved_and_published(self):
        body = self.client.get("/legacy/").content.decode()
        self.assertIn("已过审的新闻标题", body)
        # 反证：待审核 / 未发布任一条件漏掉，这两条都会出现在页面上。
        self.assertNotIn("待审核的新闻标题", body)
        self.assertNotIn("未发布的草稿标题", body)

    def test_public_news_queryset_matches_main_site_api(self):
        ids = list(public_news().values_list("id", flat=True))
        api = self.client.get("/news/news/")
        self.assertEqual(api.status_code, 200)
        payload = api.json()
        rows = payload["results"] if isinstance(payload, dict) else payload
        self.assertEqual(ids, [row["id"] for row in rows])

    def test_read_only_never_touches_cookie_or_session(self):
        response = self.client.get("/legacy/")
        self.assertEqual(response.cookies, {})
        self.assertFalse(self.client.session.keys())


class ReadOnlyMethodTest(LegacyTestCase):
    def test_write_methods_rejected_at_view_layer(self):
        from django.test import RequestFactory

        from . import views

        factory = RequestFactory()
        for view, path in ((views.home, "/legacy/"), (views.about, "/legacy/about/")):
            for method in ("post", "put", "patch", "delete"):
                response = view(getattr(factory, method)(path))
                self.assertEqual(response.status_code, 405, f"{method.upper()} {path}")
                self.assertIn("GET", response.headers["Allow"])

    def test_csrf_still_guards_the_endpoint(self):
        # 真实浏览器的 POST 在抵达视图之前就被 CSRF 中间件拦下：403 而非 405。
        # 视图自己也不接写方法（上一条测试），两道关都在。
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post("/legacy/").status_code, 403)
        self.assertEqual(strict.delete("/legacy/about/").status_code, 403)

    def test_head_is_allowed(self):
        self.assertEqual(self.client.head("/legacy/").status_code, 200)
        self.assertEqual(self.client.head("/legacy/about/").status_code, 200)


class HeaderTest(LegacyTestCase):
    def test_security_headers(self):
        for path in ("/legacy/", "/legacy/about/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response["Content-Type"].startswith("text/html; charset=utf-8"))
            self.assertEqual(
                response["Content-Security-Policy"],
                "default-src 'none'; style-src 'self'; img-src 'self'; "
                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            )
            self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            self.assertEqual(response["X-Frame-Options"], "DENY")
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response["Referrer-Policy"], "no-referrer")
            self.assertEqual(response["Cache-Control"], "public, max-age=60")

    def test_ie_user_agent_gets_same_document(self):
        # 服务端不按 UA 分流：旧浏览器拿到的是同一份 HTML，只靠 CSS 退化。
        ie8 = self.client.get("/legacy/", headers={"user-agent": IE8_UA})
        ie6 = self.client.get("/legacy/", headers={"user-agent": IE6_UA})
        modern = self.client.get("/legacy/")
        self.assertEqual(ie8.content, modern.content)
        self.assertEqual(ie6.content, modern.content)
        # 不分流就不该对 UA 分缓存：Vary 里不能出现 User-Agent。
        self.assertNotIn("user-agent", (ie8.headers.get("Vary") or "").lower())
        # 也不该依赖 Cookie：整段豁免账号中间件后，共享缓存才可能命中。
        self.assertNotIn("cookie", (ie8.headers.get("Vary") or "").lower())
        self.assertNotIn("Set-Cookie", ie8.headers)

    def test_page_is_scriptless(self):
        body = self.client.get("/legacy/").content.decode()
        self.assertNotIn("<script", body.lower())
        self.assertNotIn("javascript:", body.lower())
        self.assertIn("/static/legacy/legacy.css", body)


class SanitizeTest(TestCase):
    def setUp(self):
        AboutPage.objects.create(
            title="关于南汇一中传媒社",
            founded="2026.03",
            advisor="信息组",
            intro="<p>简介正文</p>",
        )

    def _about(self, content):
        AboutBlock.objects.create(key="story", title="我们做什么", content=content, order=1)
        return self.client.get("/legacy/about/").content.decode()

    def test_blocks_render(self):
        body = self._about("<p>正常段落</p>")
        self.assertIn("我们做什么", body)
        self.assertIn("正常段落", body)

    def test_script_removed_with_body(self):
        body = self._about("<p>前</p><script>alert('xss')</script><p>后</p>")
        self.assertNotIn("<script", body.lower())
        # 整块删除，而不是 bleach strip=True 那样把脚本源码当正文留下。
        self.assertNotIn("alert('xss')", body)
        self.assertIn("前", body)
        self.assertIn("后", body)

    def test_iframe_and_video_removed(self):
        body = self._about(
            '<iframe src="https://evil.example/x"></iframe>'
            '<video src="/media/v.mp4"></video><p>正文</p>'
        )
        self.assertNotIn("<iframe", body.lower())
        self.assertNotIn("<video", body.lower())
        self.assertNotIn("evil.example", body)
        self.assertIn("正文", body)

    def test_event_handlers_and_style_stripped(self):
        body = self._about(
            '<p style="color:red" onclick="alert(1)">带样式段落</p>'
            '<a href="/x" onmouseover="alert(2)">链接</a>'
        )
        self.assertNotIn("onclick", body.lower())
        self.assertNotIn("onmouseover", body.lower())
        self.assertNotIn("style=", body.lower())
        self.assertIn("带样式段落", body)
        self.assertIn("链接", body)

    def test_javascript_href_dropped(self):
        body = self._about('<a href="javascript:alert(1)">点我</a>')
        self.assertNotIn("javascript:", body.lower())
        self.assertIn("点我", body)
        self.assertNotIn('href="javascript', body.lower())

    def test_same_origin_image_kept(self):
        body = self._about('<p><img src="/media/news/cover.jpg" alt="封面"></p>')
        self.assertIn('src="/media/news/cover.jpg"', body)
        self.assertNotIn("外链图片未自动加载", body)

    def test_external_image_replaced_by_placeholder(self):
        body = self._about(
            '<p><img src="https://cdn.example.com/pic.png" alt="外链"></p>'
        )
        self.assertNotIn('src="https://cdn.example.com/pic.png"', body)
        self.assertIn("外链图片未自动加载", body)
        self.assertIn("cdn.example.com", body)
        self.assertIn("1 张外链图片未自动加载", body)
        self.assertIn('rel="nofollow noopener noreferrer"', body)

    def test_empty_content_still_renders(self):
        body = self._about("")
        self.assertIn("我们做什么", body)

class NewsListTest(LegacyTestCase):
    def test_list_shows_only_public_items(self):
        body = self.client.get("/legacy/news/").content.decode()
        self.assertIn("已过审的新闻标题", body)
        self.assertNotIn("待审核的新闻标题", body)
        self.assertNotIn("未发布的草稿标题", body)

    def test_list_ids_match_main_site_api_first_page(self):
        ids = list(public_news().values_list("id", flat=True)[:20])
        body = self.client.get("/legacy/news/").content.decode()
        positions = [body.find(f"/legacy/news/{pk}/") for pk in ids]
        self.assertTrue(all(p >= 0 for p in positions))
        self.assertEqual(positions, sorted(positions))

    def test_featured_only_on_unfiltered_first_page(self):
        self.approved.featured = True
        self.approved.save(update_fields=["featured"])
        first = self.client.get("/legacy/news/").content.decode()
        self.assertIn("头条", first)
        # 头条在列表里只出现一次（feature 卡与列表项互斥）
        self.assertEqual(first.count("/legacy/news/%d/" % self.approved.pk), 2)  # 卡片标题 + 缩略图/标题链接
        searched = self.client.get("/legacy/news/", {"q": "已过审"}).content.decode()
        self.assertNotIn("头条配图", searched)

    def test_search_matches_title_and_reports_empty(self):
        hit = self.client.get("/legacy/news/", {"q": "已过审"}).content.decode()
        self.assertIn("已过审的新闻标题", hit)
        miss = self.client.get("/legacy/news/", {"q": "不存在的关键词xyz"}).content.decode()
        self.assertIn("该关键词下暂无公开内容", miss)
        self.assertIn("清除筛选", miss)
        # 侧栏的「热门阅读」是全局口径、不随关键词变；只有主列该为空。
        main_col = miss.split('class="news-side"')[0]
        self.assertNotIn("已过审的新闻标题", main_col)
        self.assertIn("已过审的新闻标题", miss)

    def test_pagination_pages_and_clamps(self):
        for i in range(25):
            item = News.objects.create(
                title="分页样本 %02d" % i, author=self.author,
                is_published=True, published_at=timezone.now(),
            )
            open_review(news=item, actor=self.author, force_publish=True)
        first = self.client.get("/legacy/news/")
        self.assertEqual(first.status_code, 200)
        self.assertContains(first, "第 1 / 2 页")
        second = self.client.get("/legacy/news/", {"page": 2}).content.decode()
        self.assertIn("第 2 / 2 页", second)
        # 非法 / 越界页码不报错：退回第 1 页，或收敛到最后一页
        self.assertEqual(self.client.get("/legacy/news/", {"page": "abc"}).status_code, 200)
        clamp = self.client.get("/legacy/news/", {"page": 999}).content.decode()
        self.assertIn("第 2 / 2 页", clamp)

    def test_search_keeps_keyword_across_pages(self):
        for i in range(23):
            item = News.objects.create(
                title="搜索样本 %02d" % i, author=self.author,
                is_published=True, published_at=timezone.now(),
            )
            open_review(news=item, actor=self.author, force_publish=True)
        body = self.client.get("/legacy/news/", {"q": "搜索样本"}).content.decode()
        self.assertIn("第 1 / 2 页", body)
        self.assertIn("q=%E6%90%9C%E7%B4%A2%E6%A0%B7%E6%9C%AC", body)
        second = self.client.get("/legacy/news/", {"q": "搜索样本", "page": 2}).content.decode()
        self.assertIn("第 2 / 2 页", second)
        self.assertNotIn("已过审的新闻标题", second)

    def test_list_headers_and_no_script(self):
        response = self.client.get("/legacy/news/")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertNotIn("Set-Cookie", response.headers)
        self.assertNotIn("<script", response.content.decode().lower())


class NewsDetailTest(LegacyTestCase):
    def test_detail_renders_content(self):
        self.approved.content = "<p>正文第一段</p><h2>小标题</h2><p>第二段</p>"
        self.approved.save(update_fields=["content"])
        body = self.client.get("/legacy/news/%d/" % self.approved.pk).content.decode()
        self.assertIn("已过审的新闻标题", body)
        self.assertIn("正文第一段", body)
        self.assertIn("小标题", body)
        self.assertIn("阅读", body)
        self.assertIn("来源：传媒社", body)

    def test_hidden_items_are_404(self):
        for pk in (self.pending.pk, self.draft.pk, 999999):
            response = self.client.get("/legacy/news/%d/" % pk)
            self.assertEqual(response.status_code, 404, pk)
        body = self.client.get("/legacy/news/%d/" % self.pending.pk).content.decode()
        self.assertIn("不存在", body)
        self.assertNotIn("待审核的新闻标题", body)

    def test_detail_does_not_count_a_read(self):
        # 只读：不写 NewsView、不 +1 阅读数（主站详情才计数）
        before = News.objects.get(pk=self.approved.pk).views
        self.client.get("/legacy/news/%d/" % self.approved.pk)
        self.assertEqual(News.objects.get(pk=self.approved.pk).views, before)

    def test_detail_sanitizes_and_replaces_external_images(self):
        self.approved.content = (
            "<p>安全段落</p><script>alert('xss')</script>"
            '<img src="https://cdn.example.com/a.png" alt="外链">'
            '<img src="/media/news/local.jpg" alt="站内">'
        )
        self.approved.save(update_fields=["content"])
        body = self.client.get("/legacy/news/%d/" % self.approved.pk).content.decode()
        self.assertNotIn("<script", body.lower())
        self.assertNotIn("alert('xss')", body)
        self.assertNotIn('src="https://cdn.example.com/a.png"', body)
        self.assertIn("外链图片未自动加载", body)
        self.assertIn('src="/media/news/local.jpg"', body)

    def test_related_excludes_self(self):
        body = self.client.get("/legacy/news/%d/" % self.approved.pk).content.decode()
        self.assertNotIn("/legacy/news/%d/" % self.approved.pk + '"', body.split("相关阅读")[1] if "相关阅读" in body else "")

    def test_news_views_are_read_only(self):
        from django.test import RequestFactory

        from . import views

        factory = RequestFactory()
        cases = (
            (views.news_list, "/legacy/news/"),
            (views.news_detail, "/legacy/news/1/"),
        )
        for view, path in cases:
            for method in ("post", "put", "patch", "delete"):
                response = view(getattr(factory, method)(path), pk=1) if view is views.news_detail else view(getattr(factory, method)(path))
                self.assertEqual(response.status_code, 405, "%s %s" % (method.upper(), path))

    def test_head_allowed(self):
        self.assertEqual(self.client.head("/legacy/news/").status_code, 200)
        self.assertEqual(
            self.client.head("/legacy/news/%d/" % self.approved.pk).status_code, 200,
        )

    def test_detail_headers(self):
        response = self.client.get("/legacy/news/%d/" % self.approved.pk)
        self.assertEqual(response["Content-Security-Policy"], (
            "default-src 'none'; style-src 'self'; img-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        ))
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn("Set-Cookie", response.headers)


# ==================== PR3：活动 / 教程 ====================


class _ReviewFixtureMixin:
    """造「已过审」/「待审」对象：open_review 之后按需走一次 APPROVE。

    不能自己批自己（reviews/lifecycle 的 L-10 限制），所以另建一个持
    reviews.moderate 的审核员来执行 APPROVE。
    """

    def _make_moderator(self):
        from django.contrib.auth.models import Permission

        user = User.objects.create_user("legacy_mod", password="x")
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="reviews", codename="moderate"),
        )
        return User.objects.get(pk=user.pk)

    def _approve(self, review):
        from reviews.lifecycle import APPROVE, apply
        from reviews.models import Review

        if review is not None and review.status != Review.STATUS_APPROVED:
            apply(APPROVE, review, self.mod)
        return review


class ActivitiesTest(_ReviewFixtureMixin, LegacyTestCase):
    def setUp(self):
        super().setUp()
        from activities.models import Activity
        from reviews.lifecycle import open_review

        self.mod = self._make_moderator()
        now = timezone.now()
        common = {
            "creator": self.author,
            "status": "open",
            "body": "<p>活动正文</p>",
            "start_at": now - timedelta(hours=1),
            "end_at": now + timedelta(days=3),
        }
        self.delib = Activity.objects.create(
            type="deliberation", audience="public", title="公开众议标题", **common,
        )
        self._approve(open_review(activity=self.delib, actor=self.author))
        self.exhibition = Activity.objects.create(
            type="exhibition", audience="public", title="公开展示标题", **common,
        )
        self._approve(open_review(activity=self.exhibition, actor=self.author))
        self.survey = Activity.objects.create(
            type="survey", audience="public", title="公开调研标题", **common,
        )
        self._approve(open_review(activity=self.survey, actor=self.author))
        self.members_only = Activity.objects.create(
            type="deliberation", audience="members", title="仅成员可见标题", **common,
        )
        self._approve(open_review(activity=self.members_only, actor=self.author))
        self.pending = Activity.objects.create(
            type="deliberation", audience="public", title="待审活动标题", **common,
        )
        open_review(activity=self.pending, actor=self.author)
        self.collection = Activity.objects.create(
            type="collection", audience="public", title="征集活动标题", **common,
        )
        self._approve(open_review(activity=self.collection, actor=self.author))

    def test_list_shows_only_public_and_reviewed(self):
        body = self.client.get("/legacy/activities/").content.decode()
        for title in ("公开众议标题", "公开展示标题", "公开调研标题"):
            self.assertIn(title, body)
        # 反证：受众条件、审核条件、类型白名单任一漏掉，下面三行都会露出来。
        self.assertNotIn("仅成员可见标题", body)
        self.assertNotIn("待审活动标题", body)
        self.assertNotIn("征集活动标题", body)

    def test_list_ids_match_main_site_api(self):
        from .queries import public_activities

        api = self.client.get("/activities/activities/")
        self.assertEqual(api.status_code, 200)
        payload = api.json()
        rows = payload["results"] if isinstance(payload, dict) else payload
        self.assertEqual(
            sorted(public_activities().values_list("id", flat=True)),
            sorted(row["id"] for row in rows),
        )

    def test_type_tab_filters(self):
        body = self.client.get("/legacy/activities/", {"type": "survey"}).content.decode()
        self.assertIn("公开调研标题", body)
        self.assertNotIn("公开众议标题", body)

    def test_unknown_type_falls_back_to_all(self):
        body = self.client.get("/legacy/activities/", {"type": "bogus"}).content.decode()
        self.assertIn("公开众议标题", body)

    def test_detail_shows_vote_aggregate(self):
        from activities.models import Ballot, BallotSelection, VoteOption

        option_a = VoteOption.objects.create(activity=self.delib, text="选项甲", order=1)
        VoteOption.objects.create(activity=self.delib, text="选项乙", order=2)
        ballot = Ballot.objects.create(activity=self.delib, voter=self.author)
        BallotSelection.objects.create(ballot=ballot, option=option_a)

        body = self.client.get(f"/legacy/activities/{self.delib.pk}/").content.decode()
        self.assertIn("选项甲", body)
        self.assertIn("选项乙", body)
        # 1 票 / 1 票合计 = 100%，全在模板里算好，页面不跑脚本。
        self.assertIn("100%", body)

    def test_secret_ballot_does_not_leak_voter(self):
        from activities.models import Ballot

        self.delib.is_secret_ballot = True
        self.delib.save(update_fields=["is_secret_ballot"])
        voter = User.objects.create_user("secret_voter", password="x")
        Ballot.objects.create(activity=self.delib, voter=voter)
        body = self.client.get(f"/legacy/activities/{self.delib.pk}/").content.decode()
        # 秘密投票：连投票人是谁都不能出现在页面上。
        self.assertNotIn("secret_voter", body)

    def test_members_only_detail_is_404(self):
        response = self.client.get(f"/legacy/activities/{self.members_only.pk}/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("这个活动不存在", response.content.decode())

    def test_pending_detail_is_404(self):
        self.assertEqual(
            self.client.get(f"/legacy/activities/{self.pending.pk}/").status_code, 404,
        )

    def test_collection_detail_is_404(self):
        self.assertEqual(
            self.client.get(f"/legacy/activities/{self.collection.pk}/").status_code, 404,
        )

    def test_exhibition_shows_same_origin_cover_only(self):
        from activities.models import Exhibit
        from attachments.models import Attachment
        from common.models import ContentTarget

        with_cover = Exhibit.objects.create(activity=self.exhibition, title="有封面的展品")
        without = Exhibit.objects.create(activity=self.exhibition, title="没封面的展品")
        target = ContentTarget.objects.create(kind="exhibit", object_id=with_cover.pk)
        Attachment.objects.create(
            uploaded_by=self.author,
            target=target,
            file="attachments/demo.jpg",
            file_type="image",
            file_name="demo.jpg",
            file_size=1024,
        )
        body = self.client.get(f"/legacy/activities/{self.exhibition.pk}/").content.decode()
        self.assertIn("有封面的展品", body)
        self.assertIn("没封面的展品", body)
        self.assertIn('src="/media/attachments/demo.jpg"', body)
        self.assertIn("暂无配图", body)

    def test_survey_detail_does_not_render_questionnaire(self):
        body = self.client.get(f"/legacy/activities/{self.survey.pk}/").content.decode()
        self.assertIn("不显示问卷", body)
        # 调研表单一个输入控件都不许出现：旧浏览器提交不了，页面也绝不接收。
        for tag in ("<form", "<input", "<textarea", "<select"):
            self.assertNotIn(tag, body)

    def test_activity_body_is_sanitized(self):
        self.delib.body = '<p>正常段落</p><script>alert("x")</script>'
        self.delib.save(update_fields=["body"])
        body = self.client.get(f"/legacy/activities/{self.delib.pk}/").content.decode()
        self.assertIn("正常段落", body)
        self.assertNotIn('alert("x")', body)

    def test_home_lists_public_activities_only(self):
        body = self.client.get("/legacy/").content.decode()
        self.assertIn("近期活动", body)
        self.assertIn("公开众议标题", body)
        self.assertNotIn("仅成员可见标题", body)

    def test_detail_headers_and_no_cookie(self):
        response = self.client.get(f"/legacy/activities/{self.delib.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertTrue(response["Content-Security-Policy"].startswith("default-src 'none'"))
        self.assertEqual(response.cookies, {})

    def test_activity_views_reject_write_methods(self):
        from django.test import RequestFactory

        from . import views

        factory = RequestFactory()
        for view, path in (
            (views.activities_list, "/legacy/activities/"),
            (views.activity_detail, f"/legacy/activities/{self.delib.pk}/"),
        ):
            for method in ("post", "put", "patch", "delete"):
                response = view(getattr(factory, method)(path), pk=self.delib.pk) if "detail" in view.__name__ else view(getattr(factory, method)(path))
                self.assertEqual(response.status_code, 405, f"{method.upper()} {path}")


class TutorialsTest(_ReviewFixtureMixin, LegacyTestCase):
    def setUp(self):
        super().setUp()
        from reviews.lifecycle import open_review
        from tutorials.models import Tutorial

        self.mod = self._make_moderator()
        self.video = Tutorial.objects.create(
            title="视频教程标题",
            description="教程简介文字",
            file="tutorials/demo.mp4",
            file_type="video",
            file_name="demo.mp4",
            file_size=1048576,
            uploader=self.author,
        )
        self._approve(open_review(tutorial=self.video, actor=self.author))
        self.document = Tutorial.objects.create(
            title="文档教程标题",
            file="tutorials/demo.pdf",
            file_type="document",
            file_name="demo.pdf",
            file_size=2048,
            uploader=self.author,
        )
        self._approve(open_review(tutorial=self.document, actor=self.author))
        self.pending = Tutorial.objects.create(
            title="待审教程标题",
            file="tutorials/pending.mp4",
            file_type="video",
            file_name="pending.mp4",
            file_size=1024,
            uploader=self.author,
        )
        open_review(tutorial=self.pending, actor=self.author)

    def test_list_shows_only_approved(self):
        body = self.client.get("/legacy/tutorials/").content.decode()
        self.assertIn("视频教程标题", body)
        self.assertIn("文档教程标题", body)
        self.assertNotIn("待审教程标题", body)

    def test_list_ids_match_main_site_api(self):
        from .queries import public_tutorials

        api = self.client.get("/tutorials/tutorials/")
        self.assertEqual(api.status_code, 200)
        payload = api.json()
        rows = payload["results"] if isinstance(payload, dict) else payload
        self.assertEqual(
            sorted(public_tutorials().values_list("id", flat=True)),
            sorted(row["id"] for row in rows),
        )

    def test_detail_gives_download_link_not_embed(self):
        body = self.client.get(f"/legacy/tutorials/{self.video.pk}/").content.decode()
        self.assertIn("/media/tutorials/demo.mp4", body)
        self.assertIn("demo.mp4", body)
        # 旧浏览器不吃 <video>：页面里绝不能出现内嵌播放器。
        self.assertNotIn("<video", body)
        self.assertNotIn("<iframe", body)
        self.assertNotIn("<script", body)
        self.assertIn("不内嵌视频", body)

    def test_detail_renders_description(self):
        body = self.client.get(f"/legacy/tutorials/{self.video.pk}/").content.decode()
        self.assertIn("教程简介文字", body)

    def test_pending_detail_is_404(self):
        self.assertEqual(
            self.client.get(f"/legacy/tutorials/{self.pending.pk}/").status_code, 404,
        )

    def test_detail_headers(self):
        response = self.client.get(f"/legacy/tutorials/{self.video.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response.cookies, {})

    def test_tutorial_views_reject_write_methods(self):
        from django.test import RequestFactory

        from . import views

        factory = RequestFactory()
        self.assertEqual(views.tutorials_list(factory.post("/legacy/tutorials/")).status_code, 405)
        self.assertEqual(
            views.tutorial_detail(factory.delete("/x/"), pk=self.video.pk).status_code, 405,
        )

class AboutBlocksTest(TestCase):
    """关于页的区块级行为：全景说明、附件下载、锚点目录。"""

    def setUp(self):
        # 迁移里已经种了默认区块，这里按键覆盖而不是新建。
        AboutPage.objects.update_or_create(
            pk=1, defaults={
                "title": "关于南汇一中传媒社", "founded": "2026.03",
                "advisor": "信息组", "intro": "<p>简介正文</p>",
            },
        )
        AboutBlock.objects.update_or_create(
            key="campus-overview", defaults={
                "title": "校园全景", "order": 3,
                "content": '<iframe src="https://pano.example/view"></iframe><p>全景说明</p>',
            },
        )
        doc, _ = AboutBlock.objects.update_or_create(
            key="support", defaults={
                "title": "支持我们", "order": 4, "content": "<p>支持正文</p>",
            },
        )
        # 不落盘：只赋值文件名，url 可用、size 取不到时走「未知大小」分支。
        doc.document = "about_documents/support.pdf"
        doc.save(update_fields=["document"])

    def _body(self):
        return self.client.get("/legacy/about/").content.decode()

    def test_campus_panorama_block_only_shows_note(self):
        body = self._body()
        self.assertIn("校园全景图需要支持 WebGL 的浏览器", body)
        # 正文与 iframe 整块不输出，只保留说明。
        self.assertNotIn("全景说明", body)
        self.assertNotIn("pano.example", body)
        self.assertNotIn("<iframe", body.lower())

    def test_attachment_becomes_download_link(self):
        body = self._body()
        self.assertIn('href="/media/about_documents/support.pdf"', body)
        self.assertIn("support.pdf", body)
        self.assertIn("附件：", body)

    def test_asset_url_carries_content_hash(self):
        """CSS 链接带内容指纹：nginx 给 /static/ 7 天缓存，没有指纹就会看到旧样式。"""
        body = self._body()
        self.assertRegex(body, r'legacy\.css\?v=[0-9a-f]{8}"')

    def test_toc_links_to_every_block(self):
        body = self._body()
        self.assertIn('href="#intro"', body)
        self.assertIn('href="#block-campus-overview"', body)
        self.assertIn('href="#block-support"', body)
        self.assertIn('id="block-campus-overview"', body)
        self.assertIn('id="block-support"', body)

class RoutingTest(TestCase):
    def test_missing_trailing_slash_redirects_to_legacy_home(self):
        """少写斜杠不能掉进 SPA 兜底——那正是旧浏览器看到白屏的老路。"""
        resp = self.client.get("/legacy")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/legacy/")


class UnknownPathTest(TestCase):
    def test_unknown_legacy_path_uses_legacy_404_page(self):
        """兜底路由：不能让旧浏览器吃 Django 默认的英文纯文本 404。"""
        for path in ("/legacy/nope/", "/legacy/news/abc/"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 404, path)
            body = resp.content.decode()
            self.assertIn("这个页面不存在", body, path)
            self.assertIn("兼容性精简版", body, path)
            self.assertNotIn("Page not found", body, path)


class RateLimitTest(TestCase):
    """公开读限流：阈值临时调低，验证第 3 次请求 429 且页面仍可读、头仍齐全。"""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_third_request_is_throttled_but_still_readable(self):
        with mock.patch.object(PublicReadThrottle, "RATE", "2/min"):
            cache.clear()
            self.assertEqual(self.client.get("/legacy/").status_code, 200)
            self.assertEqual(self.client.get("/legacy/").status_code, 200)
            resp = self.client.get("/legacy/")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("请求太频繁", resp.content.decode())
        self.assertGreaterEqual(int(resp["Retry-After"]), 1)
        # 限流页同样是 legacy 页面：安全头一个不少，也不种 Cookie。
        self.assertEqual(resp["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'none'", resp["Content-Security-Policy"])
        self.assertEqual(list(resp.cookies.keys()), [])

    def test_blocked_requests_do_not_leak_other_pages(self):
        with mock.patch.object(PublicReadThrottle, "RATE", "1/min"):
            cache.clear()
            self.assertEqual(self.client.get("/legacy/news/").status_code, 200)
            resp = self.client.get("/legacy/about/")
        self.assertEqual(resp.status_code, 429)
        self.assertNotIn("关于南汇一中传媒社", resp.content.decode())
