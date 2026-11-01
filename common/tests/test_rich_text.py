from django.test import SimpleTestCase, override_settings

from common.rich_text import sanitize_html


class RichTextSanitizeTest(SimpleTestCase):
    """共享净化器 sanitize_html 的白名单契约。

    被 news（新闻正文）与 about（关于页正文）共用——任何放宽都意味着全站富文本
    暴露面变化。覆盖：iframe 嵌入闸门、脚本/事件/协议清洗、白名单标签与属性放行。

    iframe 策略（2026-08-04 起）：允许任意 https iframe（不再做平台域白名单），补偿控制
    = 仅 https + 剥 srcdoc + 服务端统一盖 sandbox（不含 allow-top-navigation）。编辑者
    为受信角色；视觉钓鱼不归代码管。
    """

    def _clean(self, html):
        return sanitize_html(html)

    # ---- iframe 嵌入闸门（任意 https iframe；非域白名单）----
    # ---- 同源 iframe 一律剥（S-3：sandbox 含 allow-same-origin，同源等于没沙箱）----
    def test_strips_same_origin_iframe(self):
        """指向本站的 iframe = 把任意落盘 HTML 当脚本执行，必须剥。"""
        out = self._clean('<iframe src="https://testserver/media/x/xss.html"></iframe>')
        self.assertNotIn("<iframe", out)

    def test_strips_protocol_relative_same_origin(self):
        out = self._clean('<iframe src="//testserver/media/x/xss.html"></iframe>')
        self.assertNotIn("<iframe", out)

    @override_settings(ALLOWED_HOSTS=[".example.com"])
    def test_strips_subdomain_of_allowed_host(self):
        out = self._clean('<iframe src="https://a.example.com/media/x.html"></iframe>')
        self.assertNotIn("<iframe", out)

    def test_keeps_cross_origin_iframe_with_sandbox(self):
        """跨源 embed（B 站 / YouTube）不受影响，sandbox 戳照旧。"""
        out = self._clean('<iframe src="https://player.bilibili.com/player.html?bvid=x"></iframe>')
        self.assertIn("<iframe", out)
        self.assertIn('sandbox="allow-scripts', out)

    def test_keeps_arbitrary_https_iframe(self):
        out = self._clean('<iframe src="https://embed.example.com/widget"></iframe>')
        self.assertIn("embed.example.com", out)
        self.assertIn("<iframe", out)

    def test_strips_http_iframe_src(self):
        # http src 被剥 → 空壳 iframe 被清（https 详情页本来也会被浏览器 mixed-content 拦）
        out = self._clean('<iframe src="http://embed.example.com/widget"></iframe>')
        self.assertNotIn("embed.example.com", out)
        self.assertNotIn("<iframe", out)

    def test_keeps_protocol_relative_iframe(self):
        # 协议相对（//host）在 https 站点即 https；常见 embed 惯例（如网易云音乐外链播放器）
        out = self._clean(
            '<iframe src="//music.163.com/outchain/player?type=2&id=3414488371&auto=1&height=66"></iframe>'
        )
        self.assertIn("music.163.com", out)
        self.assertIn("<iframe", out)
        self.assertIn('sandbox="', out)  # 协议相对也照常盖 sandbox 戳

    def test_strips_iframe_srcdoc(self):
        # srcdoc 可内嵌任意 HTML/JS，必须剥离——即使同时带 https src 作掩护
        out = self._clean(
            '<iframe src="https://embed.example.com/x" srcdoc="<script>alert(1)</script>"></iframe>'
        )
        self.assertIn("embed.example.com", out)  # 合法 https src 保留
        self.assertNotIn("srcdoc", out)
        self.assertNotIn("<script", out)

    def test_strips_iframe_event_handler(self):
        out = self._clean('<iframe src="https://embed.example.com/x" onload="alert(1)"></iframe>')
        self.assertIn("embed.example.com", out)
        self.assertNotIn("onload", out)

    def test_iframe_forced_sandbox(self):
        # 服务端统一盖 sandbox 戳（用户未给）
        out = self._clean('<iframe src="https://embed.example.com/x"></iframe>')
        self.assertIn('sandbox="allow-scripts allow-same-origin allow-popups allow-presentation"', out)

    def test_iframe_user_sandbox_overridden_no_top_navigation(self):
        # 用户粘的 sandbox（含 allow-top-navigation）必须被覆盖；出来只有一枚统一戳、且无 top-nav
        out = self._clean(
            '<iframe src="https://embed.example.com/x" sandbox="allow-scripts allow-top-navigation"></iframe>'
        )
        self.assertIn('sandbox="allow-scripts allow-same-origin allow-popups allow-presentation"', out)
        self.assertNotIn("allow-top-navigation", out)
        self.assertEqual(out.count("sandbox="), 1)

    def test_iframe_user_allow_overridden(self):
        # 用户给的 allow（含 camera/geolocation 等 Permissions-Policy）必须被覆盖为只含播放所需
        out = self._clean(
            '<iframe src="https://embed.example.com/x" allow="camera; microphone; geolocation; payment"></iframe>'
        )
        self.assertIn('allow="autoplay; fullscreen; picture-in-picture"', out)
        self.assertNotIn("camera", out)
        self.assertNotIn("geolocation", out)
        self.assertNotIn("payment", out)
        self.assertEqual(out.count("allow="), 1)

    def test_keeps_video_tag(self):
        out = self._clean('<video src="https://cdn.example.com/x.mp4" controls></video>')
        self.assertIn("<video", out)
        self.assertIn("controls", out)
        self.assertIn("cdn.example.com/x.mp4", out)

    # ---- 脚本 / 事件 / 协议清洗 ----
    def test_strips_script_tag(self):
        out = self._clean('<p>ok</p><script>alert(1)</script>')
        self.assertNotIn("<script", out)
        self.assertIn("ok", out)  # strip=True：标签剥离，正文保留

    def test_strips_event_handler_attr(self):
        out = self._clean('<img src="https://e/x.png" onerror="alert(1)">')
        self.assertNotIn("onerror", out)
        self.assertIn("e/x.png", out)

    def test_strips_javascript_protocol(self):
        out = self._clean('<a href="javascript:alert(1)">x</a>')
        self.assertNotIn("javascript:", out)

    # ---- 白名单放行 ----
    def test_keeps_allowed_tags(self):
        out = self._clean('<h2>标题</h2><p>段落 <strong>加粗</strong></p>')
        self.assertIn("<h2>", out)
        self.assertIn("<strong>", out)
        self.assertIn("<p>", out)

    def test_keeps_class_attr(self):
        out = self._clean('<span class="marker">x</span>')
        self.assertIn("class=", out)
        self.assertIn("marker", out)

    # ---- 行内样式白名单（对齐 / 文字颜色；2026-09-26 起）----
    def test_keeps_text_align_style(self):
        out = self._clean('<p style="text-align: center">x</p>')
        self.assertIn('style="text-align: center"', out)

    def test_keeps_hex_and_rgb_color_style(self):
        self.assertIn("color: #ff0000", self._clean('<span style="color: #ff0000">红</span>'))
        self.assertIn("rgb(255, 0, 0)", self._clean('<span style="color: rgb(255, 0, 0)">红</span>'))

    def test_strips_unsafe_style_props_keeps_safe(self):
        out = self._clean('<p style="position: fixed; top: 0; text-align: right">x</p>')
        self.assertNotIn("position", out)
        self.assertNotIn("top", out)
        self.assertIn("text-align: right", out)

    def test_strips_style_url_value(self):
        # url() 不在值白名单 → 值整体剥除，且不留空 style 属性
        out = self._clean('<p style="background-color: url(https://evil.example/x.png)">x</p>')
        self.assertNotIn("url", out)
        self.assertNotIn("style", out)

    def test_strips_style_expression_value(self):
        out = self._clean('<p style="color: expression(alert(1))">x</p>')
        self.assertNotIn("expression", out)
        self.assertNotIn("style", out)

    def test_style_not_allowed_on_other_tags(self):
        # style 只在 p / h1-h6 / span 上放行；img 携带 style 被剥
        out = self._clean('<img src="https://e/x.png" style="position: fixed">')
        self.assertNotIn("style", out)
        self.assertIn("e/x.png", out)

    def test_keeps_inline_marks(self):
        # 编辑器下划线 / 高亮 / 角标输出：u / mark / sub / sup
        out = self._clean("<p><u>下划线</u><mark>高亮</mark>H<sub>2</sub>O<sup>2</sup></p>")
        for frag in ("<u>", "</u>", "<mark>", "<sub>", "<sup>"):
            self.assertIn(frag, out)

    def test_style_keeps_alongside_class(self):
        out = self._clean('<span class="marker" style="color: #0a0">x</span>')
        self.assertIn("class=", out)
        self.assertIn("color: #0a0", out)

    # ---- 高亮（mark 背景色；2026-09-26 起）----
    def test_mark_keeps_background_color(self):
        # 编辑器高亮（multicolor）输出 <mark style="background-color: …; color: inherit">
        out = self._clean('<mark style="background-color: #fff3a3; color: inherit">高亮</mark>')
        self.assertIn("background-color: #fff3a3", out)
        self.assertIn("<mark", out)
        self.assertNotIn("inherit", out)  # color: inherit 值不在白名单 → 剥除

    def test_mark_strips_url_and_empty_style(self):
        out = self._clean('<mark style="background-color: url(https://evil.example/x)">x</mark>')
        self.assertNotIn("url", out)
        self.assertNotIn("style", out)  # 值被剥 → 空 style 一并清掉

    def test_mark_style_keeps_safe_strips_position(self):
        out = self._clean('<mark style="position: fixed; background-color: rgb(255, 243, 163)">x</mark>')
        self.assertNotIn("position", out)
        self.assertIn("background-color: rgb(255, 243, 163)", out)

    # ---- 边界 ----
    def test_empty_passthrough(self):
        self.assertEqual(sanitize_html(""), "")
