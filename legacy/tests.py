"""legacy 只读版测试：可见性、只读约束、安全响应头、富文本清洗。

这些断言全部走 Django test client，不依赖浏览器、不进 e2e——
Playwright 没有 IE 引擎，旧浏览器只能用「给定 UA → 断言 HTML 片段」的方式验收。
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from about.models import AboutBlock, AboutPage
from news.models import News
from reviews.lifecycle import open_review

from .queries import public_news

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
