"""「记住登录」行为（2026-10-24）：勾选 → 30 天持久 cookie；不勾 → 浏览器会话 cookie。

依据 Django 6.0.5 实现：``set_expiry(0)`` 会写 ``_session_expiry = 0``，
``get_expire_at_browser_close()`` 返回 True，SessionMiddleware 因此不下发 max-age。
"""
import json

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase


class RememberLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="remember_u", password="Passw0rd!2026")

    def _login(self, **extra):
        payload = {"username": "remember_u", "password": "Passw0rd!2026", **extra}
        return self.client.post(
            "/auth/login/", data=json.dumps(payload), content_type="application/json"
        )

    def test_remember_true_sets_persistent_cookie(self):
        resp = self._login(remember=True)
        self.assertEqual(resp.status_code, 200)
        # 服务端会话 30 天
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertAlmostEqual(
            self.client.session.get_expiry_age(), settings.REMEMBER_LOGIN_SECONDS, delta=120
        )
        # 浏览器 cookie 带 max-age
        cookie = resp.cookies[settings.SESSION_COOKIE_NAME]
        self.assertAlmostEqual(int(cookie["max-age"]), settings.REMEMBER_LOGIN_SECONDS, delta=120)

    def test_remember_absent_sets_browser_session_cookie(self):
        resp = self._login()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        # 会话 cookie：无 Max-Age
        cookie = resp.cookies[settings.SESSION_COOKIE_NAME]
        self.assertFalse(cookie["max-age"])

    def test_remember_false_explicit(self):
        resp = self._login(remember=False)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_remember_does_not_affect_login_payload(self):
        resp = self._login(remember=True)
        self.assertEqual(resp.json()["user"]["username"], "remember_u")
        self.assertIn("must_change_password", resp.json())
