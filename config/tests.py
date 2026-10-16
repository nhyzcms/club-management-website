"""配置与密钥卫生（#27）：env 化的设置项与模板的就地断言。

这里只钉「结构不变量」——限流 scope 存在、私有存储与公开 MEDIA_ROOT 隔离、
邮件后端选择函数的分支、.env.example 入库且含必要键。具体业务行为由各 app 的测试覆盖。
"""
import os
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings


class SettingsHygieneTest(TestCase):
    def test_operational_throttle_rates_not_in_settings(self):
        # Live rates come from get_policy(); settings must not be the source.
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        self.assertNotIn("register", rates)
        self.assertNotIn("resend_verification", rates)
        self.assertNotIn("feedback_anon", rates)
        self.assertNotIn("reports_user", rates)
        self.assertNotIn("login", rates)
        self.assertEqual(settings.REST_FRAMEWORK.get("NUM_PROXIES"), 1)

    def test_proxy_ssl_header_trusts_nginx(self):
        self.assertEqual(
            settings.SECURE_PROXY_SSL_HEADER,
            ("HTTP_X_FORWARDED_PROTO", "https"),
        )

    def test_hsts_seconds_follow_debug(self):
        from config import settings as cfg

        # Django 测试会把 settings.DEBUG 改成 False，但不重跑 import。测公式本身。
        self.assertEqual(cfg._https_security(True)["SECURE_HSTS_SECONDS"], 0)
        self.assertFalse(cfg._https_security(True)["SESSION_COOKIE_SECURE"])
        self.assertFalse(cfg._https_security(True)["CSRF_COOKIE_SECURE"])
        prod = cfg._https_security(False)
        self.assertEqual(prod["SECURE_HSTS_SECONDS"], 31536000)
        self.assertTrue(prod["SESSION_COOKIE_SECURE"])
        self.assertTrue(prod["CSRF_COOKIE_SECURE"])

    @override_settings(SECURE_HSTS_SECONDS=31536000, SECURE_SSL_REDIRECT=False)
    def test_hsts_header_on_https_request(self):
        resp = self.client.get("/auth/csrf/", secure=True)
        self.assertTrue(
            resp.headers["Strict-Transport-Security"].startswith("max-age=31536000"),
        )

    def test_private_media_root_is_separate_from_public_media(self):
        # 身份证明等审计留底绝不能落在公开 MEDIA_ROOT 之内（DEBUG 下后者被整目录公开服务）。
        private = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
        media = Path(settings.MEDIA_ROOT).resolve()
        self.assertNotEqual(private, media)
        self.assertNotEqual(private, media.parent)  # 不能恰好是 media 的父目录
        self.assertFalse(private.is_relative_to(media))

    def test_media_roots_derive_from_data_dir(self):
        # 统一数据根：媒体路径全部派生自 DATA_DIR（CLUB_DATA_DIR 可配置；见 docs/operations/data-root.md）。
        self.assertEqual(Path(settings.MEDIA_ROOT), Path(settings.DATA_DIR) / "media")
        self.assertEqual(
            Path(settings.PRIVATE_MEDIA_ROOT), Path(settings.DATA_DIR) / "private_media"
        )

    def test_email_backend_helper(self):
        from config import settings as cfg

        self.assertEqual(
            cfg._email_backend_for(""),
            "django.core.mail.backends.console.EmailBackend",
        )
        self.assertEqual(
            cfg._email_backend_for("someone@163.com"),
            "django.core.mail.backends.smtp.EmailBackend",
        )

    def test_allowed_hosts_parser(self):
        from config import settings as cfg

        self.assertEqual(cfg._parse_allowed_hosts(""), [])
        self.assertEqual(cfg._parse_allowed_hosts("a.com, b.com ,c.com"), ["a.com", "b.com", "c.com"])

    def test_secret_key_uses_dev_fallback_when_env_unset(self):
        # 证明 SECRET_KEY 走 env 读取 + dev 占位回退（生产用 .env 覆盖）。
        if os.environ.get("SECRET_KEY"):
            self.skipTest("SECRET_KEY 已在环境里显式设置，跳过回退断言")
        self.assertTrue(settings.SECRET_KEY)
        self.assertTrue(settings.SECRET_KEY.startswith("django-insecure-"))

    def test_secret_key_helper_empty_string_falls_back_in_debug(self):
        # .env.example 的 `SECRET_KEY=` 会把空串写进 environ；必须当未设置处理。
        from django.core.exceptions import ImproperlyConfigured

        from config import settings as cfg

        self.assertEqual(cfg._secret_key("", debug=True), cfg._DEV_SECRET_KEY)
        self.assertEqual(cfg._secret_key(None, debug=True), cfg._DEV_SECRET_KEY)
        self.assertEqual(cfg._secret_key("  real-key  ", debug=True), "real-key")
        with self.assertRaises(ImproperlyConfigured):
            cfg._secret_key("", debug=False)
        with self.assertRaises(ImproperlyConfigured):
            cfg._secret_key("   ", debug=False)

    def test_env_example_committed_with_required_keys(self):
        # .env.example 必须入库且覆盖全部需保密/可配置项。
        example = Path(settings.BASE_DIR) / ".env.example"
        self.assertTrue(example.exists(), ".env.example 必须入库")
        text = example.read_text(encoding="utf-8")
        for key in (
            "SECRET_KEY",
            "DJANGO_DEBUG",
            "ALLOWED_HOSTS",
            "FRONTEND_URL",
            "EMAIL_HOST_USER",
            "EMAIL_HOST_PASSWORD",
            "TURNSTILE_SITE_KEY",
            "TURNSTILE_SECRET_KEY",
            "UPDATE_GITHUB_TOKEN",
            "UPDATE_GITHUB_REPO",
            "CLUB_DATA_DIR",
        ):
            self.assertIn(key, text, f".env.example 缺少 {key}")
