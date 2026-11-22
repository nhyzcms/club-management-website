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
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
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
