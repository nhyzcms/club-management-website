"""身份到期前的站内提醒：还剩两个月 / 一个月各一次（只覆盖会降权的通道）。

需求：账号身份因有效性到期被降权前，前两个月 / 前一个月各发一次站内系统通知。
覆盖 ``Verification.expires_at`` 的两类降权来源：认证通道（已认证 → 未认证）与
管理员委任通道（撤销 ``is_staff``）；超管委任永久（``expires_at=null``）不提醒。
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import ValidityNotice, Verification
from accounts.validity_notices import send_expiry_notices
from messaging.models import Notification, NotificationSubscription


def make_verification(user, channel=Verification.CHANNEL_EMAIL, days=None):
    """造一条 approved 通道，``expires_at`` = 现在 + days（None = 永久）。"""
    expires_at = None if days is None else timezone.now() + timedelta(days=days)
    verification, _created = Verification.objects.update_or_create(
        user=user,
        channel=channel,
        defaults={
            "status": Verification.STATUS_APPROVED,
            "verified_at": timezone.now(),
            "expires_at": expires_at,
        },
    )
    return verification


class ExpiryNoticeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="member", password="x", email="member@163.com",
        )

    def notices(self):
        return Notification.objects.filter(recipient=self.user, category="validity")

    def test_no_notice_outside_two_month_window(self):
        make_verification(self.user, days=90)
        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 0})
        self.assertFalse(self.notices().exists())

    def test_two_month_notice_then_one_month_notice(self):
        verification = make_verification(self.user, days=59)
        self.assertEqual(send_expiry_notices()["expiring_2m"], 1)
        row = self.notices().get()
        self.assertEqual(row.event, "expiring_2m")
        self.assertEqual(row.payload["channel"], Verification.CHANNEL_EMAIL)
        self.assertEqual(row.payload["channel_label"], "邮箱认证")
        self.assertEqual(row.payload["level"], "60d")
        self.assertEqual(row.payload["url"], "/profile?tab=verification")
        self.assertEqual(
            row.payload["expires_on"],
            timezone.localtime(verification.expires_at).date().isoformat(),
        )
        self.assertTrue(
            ValidityNotice.objects.filter(verification=verification, level="60d").exists()
        )

        # 同一天再跑：幂等
        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 0})

        # 进入一个月窗口：再发一次（第二条通知）
        verification.expires_at = timezone.now() + timedelta(days=29)
        verification.save(update_fields=["expires_at"])
        self.assertEqual(send_expiry_notices()["expiring_1m"], 1)
        self.assertEqual(self.notices().count(), 2)
        self.assertEqual(
            set(self.notices().values_list("event", flat=True)),
            {"expiring_2m", "expiring_1m"},
        )

    def test_late_first_scan_only_sends_urgent_level(self):
        make_verification(self.user, days=20)
        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 1})
        self.assertEqual(self.notices().get().event, "expiring_1m")
        # 不补发过时的「两个月」提醒
        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 0})
        self.assertEqual(self.notices().count(), 1)

    def test_read_does_not_retrigger(self):
        """台账与「已读」无关：读掉提醒也不会再发一次（与未读聚合无关）。"""
        make_verification(self.user, days=20)
        send_expiry_notices()
        Notification.objects.filter(recipient=self.user).update(read_at=timezone.now())
        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 0})

    def test_renewal_starts_a_new_schedule(self):
        verification = make_verification(self.user, days=59)
        send_expiry_notices()
        # 续期一年：不再提醒
        verification.expires_at = timezone.now() + timedelta(days=365)
        verification.save(update_fields=["expires_at"])
        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 0})
        # 再临到期：重新提醒（新台账）
        verification.expires_at = timezone.now() + timedelta(days=59)
        verification.save(update_fields=["expires_at"])
        self.assertEqual(send_expiry_notices()["expiring_2m"], 1)

    def test_expired_pending_and_inactive_are_skipped(self):
        make_verification(self.user, days=-1)  # 已过期：交给 enforce_account_validity
        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 0})

        pending = User.objects.create_user(username="pending", password="x")
        make_verification(pending, days=10)
        Verification.objects.filter(user=pending).update(status=Verification.STATUS_PENDING)

        ghost = User.objects.create_user(username="ghost", password="x")
        make_verification(ghost, days=10)
        ghost.is_active = False
        ghost.save(update_fields=["is_active"])

        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 0})

    def test_appointment_channel_says_admin_identity(self):
        staff = User.objects.create_user(username="staff", password="x")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        make_verification(staff, channel=Verification.CHANNEL_APPOINTMENT, days=30)
        send_expiry_notices()
        row = Notification.objects.get(recipient=staff, category="validity")
        self.assertEqual(row.payload["channel_label"], "管理员身份")
        self.assertEqual(row.event, "expiring_1m")

    def test_superuser_without_expiry_is_never_notified(self):
        root = User.objects.create_superuser(
            username="root", password="x", email="root@163.com",
        )
        make_verification(root, channel=Verification.CHANNEL_APPOINTMENT, days=None)
        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 0})

    def test_dry_run_writes_nothing(self):
        make_verification(self.user, days=10)
        self.assertEqual(send_expiry_notices(dry_run=True)["expiring_1m"], 1)
        self.assertFalse(self.notices().exists())
        self.assertFalse(ValidityNotice.objects.exists())

    def test_user_who_muted_the_source_can_still_get_it_later(self):
        make_verification(self.user, days=10)
        NotificationSubscription.objects.create(
            user=self.user, source_key="validity", channel_key="site", enabled=False,
        )
        self.assertEqual(send_expiry_notices(), {"expiring_2m": 0, "expiring_1m": 0})
        self.assertFalse(ValidityNotice.objects.exists())  # 没送达不落账
        NotificationSubscription.objects.filter(
            user=self.user, source_key="validity",
        ).update(enabled=True)
        self.assertEqual(send_expiry_notices()["expiring_1m"], 1)


class EnforceValidityCommandNoticesTest(TestCase):
    """``enforce_validity`` 同批执行到期处理与到期前提醒。"""

    def setUp(self):
        self.user = User.objects.create_user(username="member", password="x")

    def test_command_sends_notices(self):
        make_verification(self.user, days=30)
        call_command("enforce_validity", verbosity=0)
        self.assertTrue(
            Notification.objects.filter(recipient=self.user, category="validity").exists()
        )

    def test_command_can_skip_notices(self):
        make_verification(self.user, days=30)
        call_command("enforce_validity", "--skip-notices", verbosity=0)
        self.assertFalse(
            Notification.objects.filter(recipient=self.user, category="validity").exists()
        )

    def test_expired_admin_is_demoted_without_notice(self):
        staff = User.objects.create_user(username="staff", password="x")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        make_verification(staff, channel=Verification.CHANNEL_APPOINTMENT, days=-1)
        call_command("enforce_validity", verbosity=0)
        staff.refresh_from_db()
        self.assertFalse(staff.is_staff)
        self.assertFalse(
            Notification.objects.filter(recipient=staff, category="validity").exists()
        )
