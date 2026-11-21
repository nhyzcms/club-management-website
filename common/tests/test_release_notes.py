"""release_notes 的两种读者要分开：维护者看全量，社员看人话。"""
from __future__ import annotations

import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from release_notes import render  # noqa: E402


def commit(ctype: str, summary: str, scope: str | None = None, sha: str = "abc1234"):
    return {"type": ctype, "summary": summary, "scope": scope, "sha": sha,
            "date": "2026-12-01", "subject": summary}


class ReleaseNotesTest(SimpleTestCase):
    COMMITS = [
        commit("feat", "版本号显示在页脚"),
        commit("fix", "修掉死按钮"),
        commit("ci", "恢复打包 job"),
        commit("test", "补三项断言"),
        commit("chore", "升依赖"),
    ]

    def test_changelog_entry_skips_pipeline_noise(self):
        out = render(self.COMMITS, version="1.1.0", fmt="changelog-entry")
        self.assertIn("版本号显示在页脚", out)
        self.assertIn("修掉死按钮", out)
        for noise in ("恢复打包 job", "补三项断言", "升依赖"):
            self.assertNotIn(noise, out)
        self.assertNotIn("### CI", out)
        self.assertNotIn("### Tests", out)

    def test_full_format_keeps_everything(self):
        """维护者那份不能删东西——git log 之外的记录只剩它。"""
        out = render(self.COMMITS, version="1.1.0", fmt="markdown")
        self.assertIn("恢复打包 job", out)
        self.assertIn("补三项断言", out)

    def test_all_noise_still_renders_something(self):
        out = render([commit("ci", "只有流水线改动")], version="1.1.1", fmt="changelog-entry")
        self.assertIn("没有记录到变更", out)
