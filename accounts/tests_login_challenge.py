"""陌生设备二次验证（P3）：挑战、TOTP / 恢复代码、信任落库、豁免放行。"""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from . import totp
from .utils import DEVICE_COOKIE_NAME, new_device_id
from .models import AccountDevice, LoginChallenge, LoginEvent, RecoveryCode, TotpDevice


@override_settings(LOGIN_CHALLENGE_ENABLED=True)
class LoginChallengeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ch_u", password="Passw0rd!2026")
        self.device_id = new_device_id()
        self.client.cookies[DEVICE_COOKIE_NAME] = self.device_id
        self.secret = totp.generate_secret()
        TotpDevice.objects.create(
            user=self.user,
            label="iPhone",
            secret_enc=totp.encrypt_secret(self.secret),
            confirmed_at=timezone.now(),
        )

    def _login(self, **extra):
        payload = {"username": "ch_u", "password": "Passw0rd!2026", **extra}
        return self.client.post("/auth/login/", data=json.dumps(payload), content_type="application/json")

    def _verify(self, token, **payload):
        body = {"token": token, **payload}
        return self.client.post(
            "/auth/login/challenge/verify/", data=json.dumps(body), content_type="application/json"
        )

    def test_new_device_gets_challenge_without_session(self):
        resp = self._login()
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertEqual(data["reason"], "new_device")
        self.assertIn("totp", data["methods"])
        self.assertTrue(LoginChallenge.objects.filter(token=data["challenge"]).exists())
        self.assertFalse(self.client.session.get("_auth_user_id"))
        self.assertEqual(LoginEvent.objects.get().status, "challenge")

    def test_login_without_device_cookie_still_challenges(self):
        """S-1 回归：脚本直连不带 club_device Cookie，不得跳过二次验证。

        反证：views.py 里把 `device is None or not device.is_trusted` 改回
        `device is not None and not device.is_trusted`，本条立即变红（返回 200）。
        """
        self.client.cookies.pop(DEVICE_COOKIE_NAME, None)
        resp = self._login()
        self.assertEqual(resp.status_code, 202, resp.content)
        self.assertEqual(resp.json()["reason"], "new_device")
        self.assertFalse(self.client.session.get("_auth_user_id"))
        # 202 里必须把服务端本次绑定的设备号发回来，否则验证通过后无从认设备
        self.assertIn(DEVICE_COOKIE_NAME, resp.cookies)

    def test_invalid_device_cookie_still_challenges(self):
        """非法设备号同样视为陌生设备（旧实现会返回 200）。"""
        self.client.cookies[DEVICE_COOKIE_NAME] = "not-a-valid-id"
        resp = self._login()
        self.assertEqual(resp.status_code, 202, resp.content)

    def test_verify_without_prior_device_creates_trusted_device(self):
        """无 Cookie 登录 → 挑战通过 → 设备记录补建并标记信任。"""
        self.client.cookies.pop(DEVICE_COOKIE_NAME, None)
        data = self._login().json()
        issued = self.client.cookies[DEVICE_COOKIE_NAME].value
        resp = self._verify(data["challenge"], method="totp", code=totp.code_at(self.secret))
        self.assertEqual(resp.status_code, 200, resp.content)
        device = AccountDevice.objects.get(user=self.user, device_id=issued)
        self.assertIsNotNone(device.trusted_at)
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_verify_totp_trusts_device(self):
        data = self._login().json()
        resp = self._verify(data["challenge"], method="totp", code=totp.code_at(self.secret))
        self.assertEqual(resp.status_code, 200, resp.content)
        device = AccountDevice.objects.get(user=self.user, device_id=self.device_id)
        self.assertIsNotNone(device.trusted_at)
        self.assertTrue(self.client.session.get("_auth_user_id"))
        event = LoginEvent.objects.filter(status="success").get()
        self.assertEqual(event.second_factor, "totp")

    def test_wrong_code_counts_attempts(self):
        data = self._login().json()
        resp = self._verify(data["challenge"], method="totp", code="000000")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["remaining"], 4)
        self.assertEqual(LoginChallenge.objects.get().attempts, 1)

    def test_trusted_device_skips_challenge(self):
        AccountDevice.objects.create(
            user=self.user, device_id=self.device_id, trusted_at=timezone.now()
        )
        resp = self._login()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get("must_bind_2fa"))

    def test_no_second_factor_exempts_and_keeps_device_unknown(self):
        TotpDevice.objects.all().delete()
        resp = self._login()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("must_bind_2fa"))
        event = LoginEvent.objects.filter(status="success").get()
        self.assertEqual(event.second_factor, "exempt")
        device = AccountDevice.objects.get(user=self.user, device_id=self.device_id)
        self.assertIsNone(device.trusted_at)

    def test_expired_challenge_rejected(self):
        data = self._login().json()
        LoginChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        resp = self._verify(data["challenge"], method="totp", code=totp.code_at(self.secret))
        self.assertEqual(resp.status_code, 410)

    def test_recovery_code_is_single_use(self):
        codes = totp.generate_recovery_codes(count=1)
        RecoveryCode.objects.create(user=self.user, code_hash=totp.hash_recovery_code(codes[0]))
        data = self._login().json()
        self.assertIn("recovery", data["methods"])

        resp = self._verify(data["challenge"], method="recovery", code=codes[0])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNotNone(RecoveryCode.objects.get().used_at)

        # 同一张码不能再用：新挑战 + 再用 → 400
        self.client.cookies[DEVICE_COOKIE_NAME] = new_device_id()
        again = self._login().json()
        resp = self._verify(again["challenge"], method="recovery", code=codes[0])
        self.assertEqual(resp.status_code, 400)

    def test_method_not_available_rejected(self):
        data = self._login().json()
        resp = self._verify(data["challenge"], method="email_code", code="123456")
        self.assertEqual(resp.status_code, 400)
