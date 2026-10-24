"""设备 ID、登录事件与 UA/IP 解析（账号安全中心 P0）。

原则（2026-10-24）：设备初始一律陌生；``trusted_at`` 只能由「完成一次二次验证」写入，
本模块的 UA / IP / 指纹都不参与信任判定。
"""
import json
import os
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from .devices import (
    DEVICE_COOKIE_MAX_AGE,
    DEVICE_COOKIE_NAME,
    is_valid_device_id,
    new_device_id,
    parse_device,
)
from .models import AccountDevice, LoginEvent


class DeviceCookieTests(TestCase):
    def test_first_visit_issues_device_cookie(self):
        resp = self.client.get("/auth/csrf/")
        self.assertEqual(resp.status_code, 200)
        cookie = resp.cookies[DEVICE_COOKIE_NAME]
        self.assertTrue(is_valid_device_id(cookie.value))
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(int(cookie["max-age"]), DEVICE_COOKIE_MAX_AGE)

    def test_existing_cookie_is_reused(self):
        fixed = new_device_id()
        self.client.cookies[DEVICE_COOKIE_NAME] = fixed
        resp = self.client.get("/auth/csrf/")
        self.assertNotIn(DEVICE_COOKIE_NAME, resp.cookies)

    def test_accept_ch_header_advertised(self):
        resp = self.client.get("/auth/csrf/")
        self.assertIn("Sec-CH-UA-Model", resp["Accept-CH"])


class ParseDeviceTests(TestCase):
    CHROME_WIN = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    )
    SAFARI_IOS = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    )
    WECHAT_ANDROID = (
        "Mozilla/5.0 (Linux; Android 14; SM-S918B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 "
        "Mobile Safari/537.36 MicroMessenger/8.0.47"
    )

    def test_chrome_windows(self):
        info = parse_device(self.CHROME_WIN)
        self.assertEqual(info["browser"], "Chrome")
        self.assertEqual(info["platform"], "Windows")
        # 桌面浏览器拿不到品牌型号——允许为空，不瞎猜
        self.assertEqual(info["brand"], "")
        self.assertEqual(info["model"], "")
        self.assertIn("Chrome", info["label"])

    def test_safari_ios(self):
        info = parse_device(self.SAFARI_IOS)
        self.assertEqual(info["browser"], "Safari")
        self.assertEqual(info["platform"], "iOS")
        self.assertEqual(info["model"], "iPhone")
        self.assertEqual(info["brand"], "Apple")

    def test_wechat_android_model(self):
        info = parse_device(self.WECHAT_ANDROID)
        self.assertEqual(info["browser"], "微信")
        self.assertEqual(info["platform"], "Android")
        self.assertEqual(info["model"], "SM-S918B")
        self.assertEqual(info["brand"], "Samsung")

    def test_empty_ua_does_not_crash(self):
        info = parse_device("")
        self.assertEqual(info["platform"], "未知")
        self.assertTrue(info["label"])

    def test_sec_ch_model_preferred(self):
        info = parse_device(self.WECHAT_ANDROID, sec_ch_model='"Pixel 7"')
        self.assertEqual(info["model"], "Pixel 7")
        self.assertEqual(info["brand"], "Google")


class LoginEventTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dev_u", password="Passw0rd!2026")

    def _login(self, device_id=None, password="Passw0rd!2026", **meta):
        if device_id:
            self.client.cookies[DEVICE_COOKIE_NAME] = device_id
        payload = {"username": "dev_u", "password": password}
        return self.client.post(
            "/auth/login/", data=json.dumps(payload), content_type="application/json", **meta
        )

    def test_success_creates_device_and_event(self):
        device_id = new_device_id()
        resp = self._login(device_id)
        self.assertEqual(resp.status_code, 200)

        device = AccountDevice.objects.get(user=self.user)
        self.assertEqual(device.device_id, device_id)
        # 测试客户端默认不带 User-Agent → 平台未知（不瞎猜）
        self.assertEqual(device.platform, "未知")
        # 新设备在通过二次验证前一律「不信任」
        self.assertFalse(device.is_trusted)
        self.assertIsNone(device.trusted_at)

        event = LoginEvent.objects.get()
        self.assertEqual(event.status, "success")
        self.assertTrue(event.is_new_device)
        self.assertEqual(event.device_id, device.id)
        self.assertEqual(event.user_id, self.user.id)

    def _logout(self):
        # 必须走真实登出端点：Client.logout() 直接 flush session，不会把
        # UserSession.is_current 置 False，后续登录会被 10 分钟登录保护拦成 409。
        resp = self.client.post("/auth/logout/")
        self.assertEqual(resp.status_code, 200)

    def test_second_login_same_device_is_not_new(self):
        device_id = new_device_id()
        self._login(device_id)
        self._logout()
        self._login(device_id)

        self.assertEqual(AccountDevice.objects.count(), 1)
        first, second = LoginEvent.objects.order_by("id")
        self.assertTrue(first.is_new_device)
        self.assertFalse(second.is_new_device)

    def test_different_device_creates_new_record(self):
        first = self._login(new_device_id())
        self.assertEqual(first.status_code, 200)
        self._logout()
        second = self._login(new_device_id())
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(AccountDevice.objects.count(), 2)

    def test_failed_login_records_event_without_device(self):
        resp = self._login(password="wrong-password")
        self.assertEqual(resp.status_code, 401)
        event = LoginEvent.objects.get()
        self.assertEqual(event.status, "failed")
        self.assertIsNone(event.device)
        self.assertEqual(AccountDevice.objects.count(), 0)

    def test_forwarded_for_trusted_only_from_loopback(self):
        self._login(new_device_id(), REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1")
        self.assertEqual(LoginEvent.objects.get().ip, "203.0.113.9")

        self._logout()
        LoginEvent.objects.all().delete()
        self._login(new_device_id(), REMOTE_ADDR="198.51.100.7", HTTP_X_FORWARDED_FOR="203.0.113.9")
        self.assertEqual(LoginEvent.objects.get().ip, "198.51.100.7")


@skipUnless(os.path.exists(settings.IP2REGION_DB), "ip2region xdb 未安装（CI 不下载库文件）")
class GeolocateTests(TestCase):
    def test_china_ip_resolves_city_and_coords(self):
        from .geolocate import geolocate

        geo = geolocate("114.114.114.114")
        self.assertEqual(geo["country"], "中国")
        self.assertEqual(geo["region"], "江苏")
        self.assertEqual(geo["city"], "南京")
        self.assertAlmostEqual(geo["latitude"], 32.0603, places=3)
        self.assertAlmostEqual(geo["longitude"], 118.7969, places=3)

    def test_private_ip_is_not_located(self):
        from .geolocate import geolocate

        self.assertEqual(geolocate("192.168.1.10")["city"], "")
        self.assertEqual(geolocate("127.0.0.1")["city"], "")

    def test_reserved_ip_returns_empty(self):
        from .geolocate import geolocate

        # 203.0.113.0/24 是文档保留段，ip2region 返回 Reserved
        self.assertEqual(geolocate("203.0.113.9")["country"], "")

    def test_invalid_ip_returns_empty(self):
        from .geolocate import geolocate

        self.assertEqual(geolocate("not-an-ip")["city"], "")
