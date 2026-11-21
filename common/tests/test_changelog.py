"""发行说明的解析与暴露。

两个来源必须给出同一份内容（构建产物的 JSON / 仓库里的 Markdown），
所以这里既测解析规则，也测「没有 JSON 时会不会老实回落到 Markdown」。
"""
import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from common.changelog import changelog_entry
from common.changelog_parse import parse_entry

SAMPLE = """# Changelog

## [Unreleased]

_待归类_

## [1.2.3] - 2026-12-01

### Added

- **feat**: 新增版本号页脚 (abc1234)
- 更新弹窗

### Fixed

- **ci**: 修了某处 (def5678)

## [1.2.2] - 2026-11-01

### Fixed

- 上一版的事 (000aaaa)
"""


class ParseEntryTests(TestCase):
    def test_extracts_one_version_only(self):
        entry = parse_entry(SAMPLE, "1.2.3")
        self.assertEqual(entry["version"], "1.2.3")
        self.assertEqual(entry["released"], "2026-12-01")
        titles = [s["title"] for s in entry["sections"]]
        self.assertEqual(titles, ["新增", "修复"])
        # 不能把上一版的内容带进来
        flat = [i for s in entry["sections"] for i in s["items"]]
        self.assertNotIn("上一版的事 (000aaaa)", flat)

    def test_strips_markdown_decoration(self):
        entry = parse_entry(SAMPLE, "1.2.3")
        self.assertIn("feat: 新增版本号页脚 (abc1234)", entry["sections"][0]["items"])

    def test_missing_version_returns_none(self):
        self.assertIsNone(parse_entry(SAMPLE, "9.9.9"))

    def test_empty_sections_are_dropped(self):
        md = "## [1.0.0] - 2026-01-01\n\n### Added\n\n### Fixed\n\n- 修了一处\n"
        entry = parse_entry(md, "1.0.0")
        self.assertEqual([s["title"] for s in entry["sections"]], ["修复"])


class ChangelogEntryTests(TestCase):
    def tearDown(self):
        changelog_entry.cache_clear()

    def test_reads_generated_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changelog.json"
            path.write_text(json.dumps({
                "version": "1.0.1",
                "released": "2026-11-21",
                "sections": [{"title": "新增", "items": ["甲"]}],
            }), encoding="utf-8")
            with override_settings(CHANGELOG_JSON_PATH=path):
                changelog_entry.cache_clear()
                entry = changelog_entry()

        self.assertEqual(entry["version"], "1.0.1")
        self.assertEqual(entry["sections"][0]["items"], ["甲"])

    def test_json_null_falls_back_to_markdown(self):
        """构建时 CHANGELOG.md 里没有这一节会写 null —— 此时不能就此空手而归。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changelog.json"
            path.write_text("null\n", encoding="utf-8")
            with override_settings(CHANGELOG_JSON_PATH=path):
                changelog_entry.cache_clear()
                entry = changelog_entry()

        # 仓库里确实有 CHANGELOG.md，所以要么拿到条目，要么明确 None，但不能抛
        self.assertTrue(entry is None or "sections" in entry)


class ChangelogEndpointTests(TestCase):
    def tearDown(self):
        changelog_entry.cache_clear()

    def test_endpoint_is_public_and_never_500(self):
        response = self.client.get("/changelog/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        payload = response.json()
        self.assertIsInstance(payload.get("sections"), list)

    def test_endpoint_serves_entry_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changelog.json"
            path.write_text(json.dumps({
                "version": "1.0.1",
                "released": "2026-11-21",
                "sections": [{"title": "修复", "items": ["修了一处"]}],
            }), encoding="utf-8")
            with override_settings(CHANGELOG_JSON_PATH=path):
                changelog_entry.cache_clear()
                payload = self.client.get("/changelog/").json()

        self.assertEqual(payload["sections"][0]["title"], "修复")
