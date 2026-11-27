"""版本快照的读取与暴露。

守的是「出问题时能不能一句话说清跑的是哪份代码」，所以覆盖三种情形：
镜像里读文件、本地无文件回落、文件坏了也不能 500。
"""
import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from common.version import build_info, version_string


class BuildInfoTests(TestCase):
    def tearDown(self):
        build_info.cache_clear()

    def test_reads_build_info_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "build_info.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "1.0.1",
                        "base_version": "1.0.1",
                        "channel": "release",
                        "tag": "v1.0.1",
                        "commit": "335d91e55189fcb4ecb2cf5c39c333cd21724602",
                        "commit_short": "335d91e",
                        "commits_since_tag": 0,
                        "built_at": "2026-11-21T04:31:20Z",
                        "built_by": "github-actions",
                    }
                ),
                encoding="utf-8",
            )
            with override_settings(BUILD_INFO_PATH=path):
                build_info.cache_clear()
                info = build_info()

        self.assertEqual(info["version"], "1.0.1")
        self.assertEqual(info["channel"], "release")
        self.assertEqual(info["tag"], "v1.0.1")
        self.assertEqual(info["commit_short"], "335d91e")
        self.assertEqual(info["source"], "build_info.json")

    def test_dev_build_has_suffix_and_no_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "build_info.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "1.0.1-dev.4.gabc1234",
                        "base_version": "1.0.1",
                        "channel": "dev",
                        "tag": None,
                        "commit_short": "abc1234",
                    }
                ),
                encoding="utf-8",
            )
            with override_settings(BUILD_INFO_PATH=path):
                build_info.cache_clear()
                info = build_info()

        self.assertTrue(info["version"].endswith("-dev.4.gabc1234"))
        self.assertEqual(info["channel"], "dev")
        self.assertIsNone(info["tag"])

    def test_missing_file_falls_back_to_pyproject(self):
        with override_settings(BUILD_INFO_PATH=Path("/nonexistent/build_info.json")):
            build_info.cache_clear()
            info = build_info()

        self.assertEqual(info["source"], "pyproject")
        self.assertTrue(info["version"])
        self.assertNotEqual(info["version"], "")
        # 回落路径没有 CI 信息，但不能是 None——调用方不该判空
        self.assertEqual(info["commit"], "")

    def test_broken_file_falls_back_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "build_info.json"
            path.write_text("{ this is not json", encoding="utf-8")
            with override_settings(BUILD_INFO_PATH=path):
                build_info.cache_clear()
                info = build_info()

        self.assertEqual(info["source"], "pyproject")

    def test_version_string_includes_short_commit_when_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "build_info.json"
            path.write_text(
                json.dumps({"version": "1.0.1", "commit_short": "335d91e"}),
                encoding="utf-8",
            )
            with override_settings(BUILD_INFO_PATH=path):
                build_info.cache_clear()
                self.assertEqual(version_string(), "1.0.1 (335d91e)")


class VersionEndpointTests(TestCase):
    def tearDown(self):
        build_info.cache_clear()

    def test_endpoint_is_public_and_not_cached(self):
        response = self.client.get("/version/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("version", response.json())

    def test_reports_site_environment(self):
        with override_settings(SITE_ENV="test"):
            response = self.client.get("/version/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["environment"], "test")

    def test_defaults_to_production_environment(self):
        with override_settings(SITE_ENV="production"):
            payload = self.client.get("/version/").json()
        self.assertEqual(payload["environment"], "production")

    def test_endpoint_shape_is_stable(self):
        payload = self.client.get("/version/").json()
        self.assertEqual(
            set(payload),
            {
                "version",
                "base_version",
                "channel",
                "tag",
                "commit",
                "commit_short",
                "commits_since_tag",
                "built_at",
                "built_by",
                "source",
                "environment",
            },
        )
