"""SPA 入口（index.html）必须响应 no-cache —— 这是 L0 热更新的前提。

背景（区块 8 / FEATURE-MATRIX #29）：网站更新对 App 是"零操作生效"，
壳只负责加载 index.html。dist 里的 JS/CSS 文件名带 contenthash，
HTML 一旦被 WebView 按启发式缓存，就会拿着旧哈希去要已被删除的 chunk → 白屏。

这里只断言响应头（不依赖 frontend/dist 是否构建过：临时目录里放一个最小 index.html）。
"""
import copy
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class SpaIndexNoCacheTest(SimpleTestCase):
    def setUp(self):
        self._tmpl_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self._tmpl_dir, ignore_errors=True))
        (self._tmpl_dir / "index.html").write_text(
            '<!DOCTYPE html><html><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )
        templates = copy.deepcopy(settings.TEMPLATES)
        templates[0]["DIRS"] = [str(self._tmpl_dir), *templates[0]["DIRS"]]
        self._settings_cm = self.settings(TEMPLATES=templates)
        self._settings_cm.enable()
        self.addCleanup(self._settings_cm.disable)

    def _assert_no_cache(self, path):
        resp = self.client.get(path)
        self.assertEqual(resp.status_code, 200)
        cache_control = resp["Cache-Control"]
        self.assertIn("no-store", cache_control)
        self.assertIn("no-cache", cache_control)

    def test_home_is_never_cached(self):
        self._assert_no_cache("/")

    def test_legacy_index_paths_redirect_home(self):
        """/index 与 /index.html 是历史入口，统一 302 回 `/`（不进缓存）。"""
        for path in ("/index", "/index.html"):
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertRedirects(resp, "/", status_code=302, fetch_redirect_response=False)

    def test_unknown_paths_are_404(self):
        """catch-all 已移除：非入口路径必须是 404，不能再 200 + 首页（软 404）。"""
        for path in ("/m/me", "/not-a-page", "/newsroom/2026", "/index/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
