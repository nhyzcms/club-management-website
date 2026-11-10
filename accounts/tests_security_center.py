"""账号安全中心 API（P1/P2）：总览、设备、登录记录、TOTP、恢复代码。"""
import json

from django.contrib.auth.models import User
from django.test import TestCase

from . import stepup, totp
from .models import AccountDevice, LoginEvent, RecoveryCode


def _post(client, url, payload=None, **extra):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json", **extra)


class SecurityOverviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sec_u", password="Passw0rd!2026", email="sec@example.com")
        self.client.force_login(self.user)

    def test_overview_shape(self):
        resp = self.client.get("/auth/security/overview/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["password"]["enabled"])
        self.assertTrue(data["email"]["bound"])
        self.assertTrue(data["email"]["address"].startswith("s"))
        self.assertIn("@example.com", data["email"]["address"])
        self.assertEqual(data["totp"]["count"], 0)
        self.assertEqual(data["totp"]["max"], 5)
        self.assertIn("stepup", data)

    def test_anonymous_redirected(self):
        self.client.logout()
        resp = self.client.get("/auth/security/overview/")
        self.assertEqual(resp.status_code, 302)


class DeviceApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dev_api", password="Passw0rd!2026")
        self.client.force_login(self.user)
        self.device = AccountDevice.objects.create(
            user=self.user, device_id="a" * 32, label="Chrome · Windows", platform="Windows"
        )

    def test_list_devices(self):
        resp = self.client.get("/auth/devices/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "Chrome · Windows")
        self.assertFalse(rows[0]["trusted"])

    def test_revoke_requires_stepup(self):
        resp = self.client.delete(f"/auth/devices/{self.device.id}/")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("step_up_required", resp.content.decode())

    def test_revoke_with_grant(self):
        grant = stepup.issue_grant(self.user, "manage_devices")
        resp = self.client.delete(f"/auth/devices/{self.device.id}/", HTTP_X_STEPUP_GRANT=grant)
        self.assertEqual(resp.status_code, 200)
        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.revoked_at)
        self.assertEqual(self.client.get("/auth/devices/").json()["results"], [])


class LoginEventApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ev_u", password="Passw0rd!2026")
        self.client.force_login(self.user)

    def test_pagination_and_masking(self):
        LoginEvent.objects.create(user=self.user, status="success", ip="114.114.114.114", city="南京")
        LoginEvent.objects.create(user=self.user, status="failed", ip="8.8.8.8")
        resp = self.client.get("/auth/login-events/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        ips = {row["ip"] for row in data["results"]}
        self.assertIn("114.114.*.*", ips)
        self.assertIn("8.8.*.*", ips)


class TotpApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="totp_u", password="Passw0rd!2026")
        self.client.force_login(self.user)

    PASSWORD = "Passw0rd!2026"

    def _setup(self, label="iPhone"):
        # 2026-10 起「添加因子」必须验人：step-up grant 或重输密码（此处走密码通道）
        resp = _post(self.client, "/auth/totp/setup/", {"label": label, "password": self.PASSWORD})
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def test_setup_confirm_list_delete(self):
        created = self._setup()
        self.assertTrue(created["qr"].startswith("data:image/png;base64,"))
        self.assertIn("otpauth://totp/", created["otpauth"])

        code = totp.code_at(created["secret"])
        resp = _post(self.client, "/auth/totp/confirm/", {"id": created["id"], "code": code, "password": self.PASSWORD})
        self.assertEqual(resp.status_code, 200, resp.content)
        codes = resp.json()["recovery_codes"]
        self.assertEqual(len(codes), 10)

        # 恢复代码落库为 hash，不存明文
        stored = RecoveryCode.objects.filter(user=self.user).values_list("code_hash", flat=True)
        self.assertTrue(any(totp.hash_recovery_code(c) in stored for c in codes))

        listing = self.client.get("/auth/totp/").json()
        self.assertEqual(len(listing["results"]), 1)

        # 删除需要 stepup
        self.assertEqual(self.client.delete(f"/auth/totp/{created['id']}/").status_code, 403)
        grant = stepup.issue_grant(self.user, "manage_totp")
        resp = self.client.delete(f"/auth/totp/{created['id']}/", HTTP_X_STEPUP_GRANT=grant)
        self.assertEqual(resp.status_code, 200)

    def test_confirm_rejects_wrong_code(self):
        created = self._setup()
        resp = _post(self.client, "/auth/totp/confirm/", {"id": created["id"], "code": "000000", "password": self.PASSWORD})
        self.assertEqual(resp.status_code, 400)

    def test_pending_overflow_keeps_newest_setup(self):
        """pending 满额时只清旧的：刚返回给前端的那条二维码必须仍然有效。"""
        from .models import TotpDevice

        old_ids = [self._setup(f"p{i}")["id"] for i in range(totp.MAX_PENDING_TOTP)]
        newest = self._setup("just-scanned")

        self.assertTrue(
            TotpDevice.objects.filter(pk=newest["id"], confirmed_at__isnull=True).exists()
        )
        pending = TotpDevice.objects.filter(user=self.user, confirmed_at__isnull=True)
        self.assertLessEqual(pending.count(), totp.MAX_PENDING_TOTP)
        self.assertFalse(TotpDevice.objects.filter(pk=old_ids[0]).exists())

    def test_stale_pending_cleaned_before_fresh(self):
        """超过 TTL 未确认的记录优先被清，新记录不受影响。"""
        from datetime import timedelta

        from django.utils import timezone

        from .models import TotpDevice

        stale = self._setup("old")
        TotpDevice.objects.filter(pk=stale["id"]).update(
            created_at=timezone.now() - timedelta(minutes=totp.PENDING_TTL_MINUTES + 1)
        )
        for i in range(totp.MAX_PENDING_TOTP - 1):
            self._setup(f"new{i}")

        fresh = self._setup("fresh")
        self.assertFalse(TotpDevice.objects.filter(pk=stale["id"]).exists())
        self.assertTrue(TotpDevice.objects.filter(pk=fresh["id"]).exists())

    def test_totp_limit(self):
        from .models import TotpDevice
        from django.utils import timezone

        for i in range(5):
            TotpDevice.objects.create(
                user=self.user, label=f"t{i}", secret_enc=totp.encrypt_secret(totp.generate_secret()),
                confirmed_at=timezone.now(),
            )
        resp = _post(self.client, "/auth/totp/setup/", {"label": "one-too-many", "password": self.PASSWORD})
        self.assertEqual(resp.status_code, 400)

    def test_recovery_regenerate_requires_stepup(self):
        self.assertEqual(_post(self.client, "/auth/recovery-codes/").status_code, 403)
        grant = stepup.issue_grant(self.user, "manage_totp")
        resp = _post(self.client, "/auth/recovery-codes/", {}, HTTP_X_STEPUP_GRANT=grant)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 10)


class TotpFactorGuardTests(TestCase):
    """添加二次验证因子必须验人 —— 生产 XSS 链的关键一环。

    攻击链（2026-10 实测）：XSS 拿到会话 → 无验证地给自己加一个 TOTP
    （setup + confirm）→ 用它通过 change_password 的 step-up → 爆破旧密码改密
    → 接管账号（管理员即提权）。加因子这道闸就是切断它。

    反证：把 ``_guard_factor_change`` 的调用删掉，本类 4 条用例立即变红。
    """

    PASSWORD = "Passw0rd!2026"

    def setUp(self):
        self.user = User.objects.create_user(username="totp_guard", password=self.PASSWORD)
        self.client.force_login(self.user)

    def test_setup_requires_identity_when_no_grant(self):
        """只有会话、没有密码 → 拿不到 secret（这就是 XSS 攻击者的处境）。"""
        resp = _post(self.client, "/auth/totp/setup/", {"label": "x"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["reason"], "password_required")

    def test_setup_rejects_wrong_password(self):
        resp = _post(self.client, "/auth/totp/setup/", {"label": "x", "password": "not-the-password"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["reason"], "password_required")

    def test_setup_accepts_correct_password(self):
        resp = _post(self.client, "/auth/totp/setup/", {"label": "x", "password": self.PASSWORD})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("secret", resp.json())

    def test_setup_accepts_stepup_grant(self):
        grant = stepup.issue_grant(self.user, "manage_totp")
        resp = _post(self.client, "/auth/totp/setup/", {"label": "x"}, HTTP_X_STEPUP_GRANT=grant)
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_confirm_also_guarded(self):
        """setup 通过后，裸 confirm（不带密码 / grant）仍要被拦。"""
        created = _post(
            self.client, "/auth/totp/setup/", {"label": "x", "password": self.PASSWORD},
        ).json()
        code = totp.code_at(created["secret"])
        resp = _post(self.client, "/auth/totp/confirm/", {"id": created["id"], "code": code})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["reason"], "password_required")

    def test_grant_from_other_scope_is_not_enough(self):
        """别的 scope 的 grant 不能用来加因子（防越权复用令牌）。"""
        grant = stepup.issue_grant(self.user, "change_password")
        resp = _post(self.client, "/auth/totp/setup/", {"label": "x"}, HTTP_X_STEPUP_GRANT=grant)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["reason"], "password_required")
