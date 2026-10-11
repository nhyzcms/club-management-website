"""账号身份有效期（ADR-0041）：认证/管理员/注册宽限三档规则 + 权限层级门控。

覆盖：认证过期回落访客、管理员委任 2 年 / 超管永久、未认证超期停用 + 登录专属提示、
超级管理员豁免、rank_of / can_manage_validity_for、认证码过期可重新兑换、管理命令 dry-run。
"""
import json
from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from common.models import SiteSettings

from accounts.authcode import AuthCodeError, redeem_authcode
from accounts.models import (
    AuthCode,
    Profile,
    Verification,
    admin_identity_valid,
    can_manage_validity_for,
    has_ever_verified,
    is_verified,
    rank_of,
)
from accounts.validity import enforce_account_validity

LOGIN_URL = "/auth/login/"


def set_policy(**kwargs):
    obj, _ = SiteSettings.objects.get_or_create(pk=1)
    for key, value in kwargs.items():
        setattr(obj, key, value)
    obj.save()
    return obj


def approve(user, channel=Verification.CHANNEL_MANUAL, *, expires_at=None, days=365):
    """造一条 approved 通道（含 verified_at 与可定制 expires_at）。"""
    return Verification.objects.create(
        user=user,
        channel=channel,
        status=Verification.STATUS_APPROVED,
        verified_at=timezone.now(),
        expires_at=expires_at if expires_at is not None else timezone.now() + timedelta(days=days),
    )


def backdate_joined(user, days):
    User.objects.filter(pk=user.pk).update(
        date_joined=timezone.now() - timedelta(days=days),
    )
    user.refresh_from_db()
    return user


def grant_manage_validity(user):
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="accounts", codename="manage_validity")
    )
    return User.objects.get(pk=user.pk)


class IsVerifiedExpiryTest(TestCase):
    def test_verified_with_future_expiry(self):
        u = User.objects.create_user(username="u", password="p")
        approve(u)
        self.assertTrue(is_verified(u))
        self.assertTrue(has_ever_verified(u))

    def test_verified_with_past_expiry_is_not_verified(self):
        u = User.objects.create_user(username="u", password="p")
        approve(u, expires_at=timezone.now() - timedelta(days=1))
        self.assertFalse(is_verified(u))
        # 曾验证过 → 不触发 60 天停用
        self.assertTrue(has_ever_verified(u))

    def test_permanent_channel_never_expires(self):
        u = User.objects.create_user(username="u", password="p")
        approve(u, expires_at=None)
        self.assertTrue(is_verified(u))

    def test_superuser_always_verified(self):
        u = User.objects.create_superuser("su", "s@e.com", "p")
        self.assertTrue(is_verified(u))
        self.assertTrue(admin_identity_valid(u))


class AdminIdentityTest(TestCase):
    def test_staff_appointment_valid(self):
        u = User.objects.create_user(username="a", password="p", is_staff=True)
        # post_save 已建 appointment 通道（expires_at = now + 730d）
        self.assertTrue(admin_identity_valid(u))
        self.assertTrue(is_verified(u))

    def test_staff_appointment_expired(self):
        u = User.objects.create_user(username="a", password="p", is_staff=True)
        v = u.verifications.get(channel=Verification.CHANNEL_APPOINTMENT)
        v.expires_at = timezone.now() - timedelta(days=1)
        v.save(update_fields=["expires_at"])
        self.assertFalse(admin_identity_valid(u))
        self.assertFalse(is_verified(u))

    def test_superuser_admin_identity_always_valid(self):
        u = User.objects.create_superuser("su", "s@e.com", "p")
        self.assertTrue(admin_identity_valid(u))


class RankOfTest(TestCase):
    def test_rank_hierarchy(self):
        su = User.objects.create_superuser("su", "s@e.com", "p")
        staff = User.objects.create_user(username="staff", password="p", is_staff=True)
        verified = User.objects.create_user(username="v", password="p")
        approve(verified)
        unverified = User.objects.create_user(username="g", password="p")
        self.assertEqual(rank_of(su), 3)
        self.assertEqual(rank_of(staff), 2)
        self.assertEqual(rank_of(verified), 1)
        self.assertEqual(rank_of(unverified), 0)


class CanManageValidityForTest(TestCase):
    def test_staff_without_perm_cannot_edit(self):
        staff = User.objects.create_user(username="staff", password="p", is_staff=True)
        target = User.objects.create_user(username="t", password="p")
        self.assertFalse(can_manage_validity_for(staff, target))

    def test_staff_with_perm_edits_lower(self):
        staff = grant_manage_validity(
            User.objects.create_user(username="staff", password="p", is_staff=True)
        )
        verified = User.objects.create_user(username="v", password="p")
        approve(verified)
        unverified = User.objects.create_user(username="g", password="p")
        self.assertTrue(can_manage_validity_for(staff, verified))
        self.assertTrue(can_manage_validity_for(staff, unverified))

    def test_staff_cannot_edit_peer_or_superuser(self):
        staff = grant_manage_validity(
            User.objects.create_user(username="staff", password="p", is_staff=True)
        )
        peer = User.objects.create_user(username="peer", password="p", is_staff=True)
        su = User.objects.create_superuser("su", "s@e.com", "p")
        self.assertFalse(can_manage_validity_for(staff, peer))
        self.assertFalse(can_manage_validity_for(staff, su))

    def test_superuser_edits_staff_but_not_superuser(self):
        su = User.objects.create_superuser("su", "s@e.com", "p")
        staff = User.objects.create_user(username="staff", password="p", is_staff=True)
        su2 = User.objects.create_superuser("su2", "s2@e.com", "p")
        self.assertTrue(can_manage_validity_for(su, staff))
        self.assertFalse(can_manage_validity_for(su, su2))


class EnforceAccountValidityTest(TestCase):
    def test_unverified_after_grace_is_disabled(self):
        u = User.objects.create_user(username="u", password="p")
        backdate_joined(u, 61)
        self.assertEqual(enforce_account_validity(u), "unverified_expired")
        u.refresh_from_db()
        self.assertFalse(u.is_active)
        self.assertIsNotNone(u.profile.expiry_disabled_at)

    def test_unverified_within_grace_not_disabled(self):
        u = User.objects.create_user(username="u", password="p")
        backdate_joined(u, 30)
        self.assertIsNone(enforce_account_validity(u))
        u.refresh_from_db()
        self.assertTrue(u.is_active)

    def test_verified_user_not_disabled_even_if_old(self):
        u = User.objects.create_user(username="u", password="p")
        approve(u)
        backdate_joined(u, 400)
        self.assertIsNone(enforce_account_validity(u))
        u.refresh_from_db()
        self.assertTrue(u.is_active)

    def test_registration_deadline_override_extends(self):
        u = User.objects.create_user(username="u", password="p")
        backdate_joined(u, 61)
        Profile.objects.create(user=u, registration_deadline=timezone.now() + timedelta(days=1))
        self.assertIsNone(enforce_account_validity(u))
        u.refresh_from_db()
        self.assertTrue(u.is_active)

    def test_staff_admin_expiry_demotes(self):
        u = User.objects.create_user(username="a", password="p", is_staff=True)
        v = u.verifications.get(channel=Verification.CHANNEL_APPOINTMENT)
        v.expires_at = timezone.now() - timedelta(days=1)
        v.save(update_fields=["expires_at"])
        self.assertEqual(enforce_account_validity(u), "admin_expired")
        u.refresh_from_db()
        self.assertFalse(u.is_staff)

    def test_superuser_exempt(self):
        u = User.objects.create_superuser("su", "s@e.com", "p")
        backdate_joined(u, 1000)
        self.assertIsNone(enforce_account_validity(u))
        self.assertTrue(u.is_superuser)
        self.assertTrue(u.is_active)

    def test_idempotent_after_disable(self):
        u = User.objects.create_user(username="u", password="p")
        backdate_joined(u, 61)
        self.assertEqual(enforce_account_validity(u), "unverified_expired")
        self.assertIsNone(enforce_account_validity(u))  # 已停用 → no-op

    def test_dry_run_does_not_mutate(self):
        u = User.objects.create_user(username="u", password="p")
        backdate_joined(u, 61)
        self.assertEqual(enforce_account_validity(u, dry_run=True), "unverified_expired")
        u.refresh_from_db()
        self.assertTrue(u.is_active)


class LoginExpiredMessageTest(TestCase):
    """登录时未认证超期账号返回专属提示（reason=account_expired_unverified）。"""

    def _login(self, username, password):
        return Client().post(
            LOGIN_URL,
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )

    def test_fresh_expiry_at_login_shows_specific_message(self):
        u = User.objects.create_user(username="u", password="secret123")
        backdate_joined(u, 61)
        resp = self._login("u", "secret123")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "account_expired_unverified")
        self.assertIn("60 日未认证", resp.json()["error"])

    def test_already_disabled_by_cron_shows_specific_message(self):
        u = User.objects.create_user(username="u", password="secret123")
        backdate_joined(u, 61)
        enforce_account_validity(u)  # 模拟 cron 已停用
        u.refresh_from_db()
        self.assertFalse(u.is_active)
        resp = self._login("u", "secret123")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "account_expired_unverified")

    def test_manually_disabled_verified_account_keeps_generic_message(self):
        u = User.objects.create_user(username="u", password="secret123")
        approve(u)
        u.is_active = False
        u.save(update_fields=["is_active"])
        resp = self._login("u", "secret123")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "account_disabled")


class AuthCodeRedeemExpiryTest(TestCase):
    """认证码通过设 expires_at；认证过期后可重新兑换（重新认证）。"""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(username="u", password="p")

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _make_code(self, code, expires_in=timedelta(days=1)):
        return AuthCode.objects.create(code=code, expires_at=timezone.now() + expires_in)

    def test_redeem_sets_expiry(self):
        self._make_code("AAAA00000000")
        redeem_authcode(self.user, "AAAA00000000")
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_AUTHCODE)
        self.assertIsNotNone(v.expires_at)
        self.assertGreater(v.expires_at, timezone.now())
        self.assertTrue(is_verified(self.user))

    def test_redeem_blocked_while_still_valid(self):
        self._make_code("AAAA00000000")
        redeem_authcode(self.user, "AAAA00000000")
        self._make_code("BBBB00000000")
        with self.assertRaises(AuthCodeError):
            redeem_authcode(self.user, "BBBB00000000")

    def test_redeem_allowed_after_expiry(self):
        self._make_code("AAAA00000000")
        redeem_authcode(self.user, "AAAA00000000")
        v = Verification.objects.get(user=self.user, channel=Verification.CHANNEL_AUTHCODE)
        v.expires_at = timezone.now() - timedelta(days=1)
        v.save(update_fields=["expires_at"])
        self.assertFalse(is_verified(self.user))

        self._make_code("BBBB00000000")
        redeem_authcode(self.user, "BBBB00000000")  # 不抛 → 重新认证成功
        v.refresh_from_db()
        self.assertGreater(v.expires_at, timezone.now())
        self.assertTrue(is_verified(self.user))


class ManageValidityGrantMigrationTest(TestCase):
    def test_groups_received_manage_validity(self):
        for name in ("社长", "信息组"):
            group = Group.objects.get(name=name)
            got = set(
                group.permissions.filter(content_type__app_label="accounts")
                .values_list("codename", flat=True)
            )
            self.assertIn("manage_validity", got, f"{name} 缺少 manage_validity")
