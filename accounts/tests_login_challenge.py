"""陌生设备二次验证（P3）：挑战、TOTP / 恢复代码、信任落库、豁免放行。"""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from . import totp
from .devices import DEVICE_COOKIE_NAME, new_device_id
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
