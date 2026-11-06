"""审计 #272 / #275：nginx 配置漂移自检。

`client_max_body_size` 有三个「真源」：站点策略表、`scripts/install.sh` 模板、
线上 `/etc/nginx/conf.d/*.conf`。前两者跟代码走，第三者不跟——于是出现过
「仓库 600M、线上 20M、测试全绿、用户 21MB 就 413」的局面。

这里测的是 `nginx_doctor` 的解析与判定逻辑（纯函数 + 用样例配置跑命令）。
"""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from common.management.commands.nginx_doctor import (
    body_size_directives,
    missing_media_headers,
    parse_size,
)

#: 线上 2026-11-06 的实际形态（简化）：20M 且 /media/ 无任何头。
DRIFTED = """
http {
    server {
        listen 80;
        client_max_body_size 20M;
        location /media/ {
            alias /opt/club/data/media/;
            expires 7d;
        }
    }
}
"""

#: 修好之后的目标形态。
FIXED = """
http {
    server {
        listen 80;
        client_max_body_size 600M;
        location /media/ {
            alias /opt/club/data/media/;
            expires 7d;
            add_header X-Content-Type-Options nosniff always;
            add_header X-Frame-Options SAMEORIGIN always;
            add_header Content-Security-Policy "default-src 'none'" always;
        }
        error_page 413 = @payload_too_large;
        location @payload_too_large {
            default_type application/json;
            return 413 '{"reason":"payload_too_large"}';
        }
    }
}
"""


class ParseSizeTest(SimpleTestCase):
    def test_units(self):
        self.assertEqual(parse_size("600M"), 600 * 1024 ** 2)
        self.assertEqual(parse_size("20m"), 20 * 1024 ** 2)
        self.assertEqual(parse_size("1G"), 1024 ** 3)
        self.assertEqual(parse_size("1024"), 1024)
        self.assertEqual(parse_size(" 50 M "), 50 * 1024 ** 2)

    def test_garbage_is_none(self):
        for value in ("", "abc", "10X", "-5M", None):
            self.assertIsNone(parse_size(value), value)


class BodySizeDirectivesTest(SimpleTestCase):
    def test_collects_every_directive(self):
        """多个 server 块各有自己的值，必须全部收上来（取最小值判漂移）。"""
        config = "client_max_body_size 600M;\nserver { client_max_body_size 20M; }"
        self.assertEqual(
            sorted(body_size_directives(config)),
            sorted([600 * 1024 ** 2, 20 * 1024 ** 2]),
        )

    def test_missing_directive_is_empty_list(self):
        self.assertEqual(body_size_directives("server { listen 80; }"), [])


class MediaHeadersTest(SimpleTestCase):
    def test_detects_missing_headers(self):
        self.assertEqual(
            sorted(missing_media_headers(DRIFTED)),
            sorted([
                "X-Content-Type-Options", "X-Frame-Options", "Content-Security-Policy",
            ]),
        )

    def test_fixed_config_has_none_missing(self):
        self.assertEqual(missing_media_headers(FIXED), [])

    def test_no_media_location_is_not_a_drift(self):
        """没有 /media/ location 属于另一类问题，这里不重复报警。"""
        self.assertEqual(missing_media_headers("server { listen 80; }"), [])


class NginxDoctorCommandTest(TestCase):
    def tearDown(self):
        import tempfile, os
        for path in getattr(self, "_tempfiles", []):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _run(self, config: str, **kwargs):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".conf", delete=False, encoding="utf-8",
        )
        handle.write(config)
        handle.close()
        self._tempfiles = getattr(self, "_tempfiles", []) + [handle.name]
        self._last_output = ""
        out = StringIO()
        try:
            call_command("nginx_doctor", "--nginx-conf", handle.name, stdout=out, **kwargs)
        finally:
            self._last_output = out.getvalue()
        return self._last_output

    def _run_capturing(self, config: str, **kwargs):
        """跑命令、返回 stdout——即使它因为漂移抛了 CommandError。"""
        try:
            return self._run(config, **kwargs)
        except CommandError:
            return self._last_output

    def test_drift_exits_non_zero(self):
        """这条就是在复现线上：20M < 策略，且 /media/ 无头。"""
        with self.assertRaises(CommandError) as ctx:
            self._run(DRIFTED)
        message = str(ctx.exception)
        self.assertIn("漂移", message)

    def test_drift_json_reports_both_problems(self):
        # 命令在报告漂移后会抛 CommandError（给脚本拿退出码用），JSON 已经写到 stdout。
        import json as _json

        out = self._run_capturing(DRIFTED, json=True)

        payload = _json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["client_max_body_sizes"], [20 * 1024 ** 2])
        self.assertTrue(payload["missing_media_headers"])
        joined = " ".join(payload["problems"])
        self.assertIn("client_max_body_size", joined)
        self.assertIn("/media/", joined)

    def test_fixed_config_passes(self):
        out = self._run(FIXED)
        self.assertIn("一致", out)

    def test_required_bytes_override(self):
        """--required-bytes 可以脱离 DB 单独验（部署脚本里也能用）。"""
        out = self._run(FIXED, required_bytes=1024)
        self.assertIn("一致", out)
        with self.assertRaises(CommandError):
            self._run(FIXED, required_bytes=10 ** 12)

    def test_overshoot_warns_but_passes(self):
        """600M 兜底 vs 策略 50M：超过 4× 只提醒，不算漂移（不该阻断部署）。"""
        config = FIXED.replace("600M", "100G")
        out = self._run(config, required_bytes=50 * 1024 ** 2)
        self.assertIn("过宽", out)
