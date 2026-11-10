"""Turnstile 开关与 siteverify 校验。"""
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from django.test import SimpleTestCase, override_settings

from accounts.turnstile import (
    SITEVERIFY_URL,
    is_turnstile_enabled,
    public_turnstile_fields,
    verify_turnstile,
)


class _FakeResp:
    def __init__(self, body: str):
        self._buf = BytesIO(body.encode())

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TurnstileGateTest(SimpleTestCase):
    @override_settings(TURNSTILE_SITE_KEY="", TURNSTILE_SECRET_KEY="")
    def test_both_empty_is_off(self):
        self.assertFalse(is_turnstile_enabled())
        self.assertEqual(
            public_turnstile_fields(),
            {"turnstile_enabled": False, "turnstile_site_key": ""},
        )
        self.assertTrue(verify_turnstile(""))

    @override_settings(TURNSTILE_SITE_KEY="  ", TURNSTILE_SECRET_KEY="  ")
    def test_whitespace_only_is_off(self):
        self.assertFalse(is_turnstile_enabled())
        self.assertTrue(verify_turnstile("dummy"))

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="")
    def test_sitekey_only_is_off_and_does_not_leak_key(self):
        self.assertFalse(is_turnstile_enabled())
        self.assertEqual(
            public_turnstile_fields(),
            {"turnstile_enabled": False, "turnstile_site_key": ""},
        )
        self.assertTrue(verify_turnstile(""))

    @override_settings(TURNSTILE_SITE_KEY="", TURNSTILE_SECRET_KEY="secret")
    def test_secret_only_is_off(self):
        self.assertFalse(is_turnstile_enabled())
        self.assertTrue(verify_turnstile(""))

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="secret")
    def test_both_set_is_on_and_exposes_sitekey(self):
        self.assertTrue(is_turnstile_enabled())
        self.assertEqual(
            public_turnstile_fields(),
            {"turnstile_enabled": True, "turnstile_site_key": "site"},
        )

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="secret")
    def test_enabled_empty_token_rejected(self):
        self.assertFalse(verify_turnstile(""))


class TurnstileSiteverifyTest(SimpleTestCase):
    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="secret")
    @patch("accounts.turnstile.urllib.request.urlopen")
    def test_cloudflare_success(self, mock_open):
        mock_open.return_value = _FakeResp('{"success": true}')
        self.assertTrue(verify_turnstile("tok", "1.2.3.4"))
        req = mock_open.call_args[0][0]
        self.assertEqual(req.full_url, SITEVERIFY_URL)

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="secret")
    @patch("accounts.turnstile.urllib.request.urlopen")
    def test_cloudflare_failure(self, mock_open):
        mock_open.return_value = _FakeResp('{"success": false}')
        self.assertFalse(verify_turnstile("tok"))

    @override_settings(TURNSTILE_SITE_KEY="site", TURNSTILE_SECRET_KEY="secret")
    @patch("accounts.turnstile.urllib.request.urlopen", side_effect=URLError("timeout"))
    def test_network_error_rejected(self, _mock_open):
        self.assertFalse(verify_turnstile("tok"))
