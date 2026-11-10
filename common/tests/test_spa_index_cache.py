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

    def test_spa_catch_all_is_never_cached(self):
        """`/m/me`、`/#/news` 之类的深链接都落到同一条兜底路由。"""
        self._assert_no_cache("/m/me")
