"""Site policy singleton: defaults, cache invalidation, public GET."""
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from common.admin import SiteSettingsAdmin
from common.models import SiteSettings
from common.policy import (
    DEFAULT_AUTHCODE_REDEEM_PER_USER_PER_HOUR,
    DEFAULT_AUTO_UPDATE_ENABLED,
    DEFAULT_COMMENT_MAX_DEPTH,
    DEFAULT_FEEDBACK_ANON_PER_IP_PER_DAY,
    DEFAULT_LOGIN_PER_IP_PER_HOUR,
    DEFAULT_LOGIN_PER_USERNAME_PER_HOUR,
    DEFAULT_MEMBER_CHECK_PER_IP_PER_HOUR,
    DEFAULT_MEMBER_LOOKUP_PER_IP_PER_HOUR,
    DEFAULT_MEMBER_CLAIM_ENABLED,
    DEFAULT_MEMBER_CLAIM_PER_IP_PER_DAY,
    DEFAULT_MEMBER_CLAIM_PER_USER_PER_HOUR,
    DEFAULT_STEPUP_EMAIL_PER_IP_PER_HOUR,
    DEFAULT_STEPUP_EMAIL_PER_USER_PER_HOUR,
    DEFAULT_REGISTER_PER_IP_PER_DAY,
    DEFAULT_REPORTS_PER_USER_PER_DAY,
    DEFAULT_RESEND_VERIFICATION_PER_IP_PER_HOUR,
    DEFAULT_SYNC_UPLOAD_MAX_BYTES,
    DEFAULT_TUS_MEDIA_MAX_BYTES,
    DEFAULT_UPDATE_APPLY_CUTOFF_MINUTES_BEFORE_END,
    DEFAULT_UPDATE_DB_BACKUP_KEEP,
    DEFAULT_UPDATE_POLL_INTERVAL_SECONDS,
    DEFAULT_UPDATE_RELEASE_KEEP,
    DEFAULT_UPDATE_TIMEZONE,
    DEFAULT_UPDATE_WINDOW_END_HOUR,
    DEFAULT_UPDATE_WINDOW_START_HOUR,
    get_policy,
    invalidate_policy_cache,
)


class SitePolicyDefaultsTest(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_missing_row_returns_today_hardcoded_defaults(self):
        self.assertFalse(SiteSettings.objects.exists())
        p = get_policy()
        self.assertTrue(p.verification_enabled)
        self.assertTrue(p.content_review_enabled)
        self.assertTrue(p.registration_enabled)
        self.assertEqual(p.register_per_ip_per_day, DEFAULT_REGISTER_PER_IP_PER_DAY)
        self.assertEqual(
            p.resend_verification_per_ip_per_hour,
            DEFAULT_RESEND_VERIFICATION_PER_IP_PER_HOUR,
        )
        self.assertEqual(p.login_per_ip_per_hour, DEFAULT_LOGIN_PER_IP_PER_HOUR)
        self.assertEqual(p.login_per_username_per_hour, DEFAULT_LOGIN_PER_USERNAME_PER_HOUR)
        self.assertEqual(p.feedback_anon_per_ip_per_day, DEFAULT_FEEDBACK_ANON_PER_IP_PER_DAY)
        self.assertEqual(p.reports_per_user_per_day, DEFAULT_REPORTS_PER_USER_PER_DAY)
        self.assertEqual(p.authcode_redeem_per_user_per_hour, DEFAULT_AUTHCODE_REDEEM_PER_USER_PER_HOUR)
        self.assertEqual(p.member_claim_enabled, DEFAULT_MEMBER_CLAIM_ENABLED)
        self.assertEqual(p.member_claim_per_user_per_hour, DEFAULT_MEMBER_CLAIM_PER_USER_PER_HOUR)
        self.assertEqual(p.member_claim_per_ip_per_day, DEFAULT_MEMBER_CLAIM_PER_IP_PER_DAY)
        self.assertEqual(p.member_check_per_ip_per_hour, DEFAULT_MEMBER_CHECK_PER_IP_PER_HOUR)
        self.assertEqual(
            p.member_lookup_per_ip_per_hour, DEFAULT_MEMBER_LOOKUP_PER_IP_PER_HOUR
        )
        self.assertEqual(p.stepup_email_per_user_per_hour, DEFAULT_STEPUP_EMAIL_PER_USER_PER_HOUR)
        self.assertEqual(p.stepup_email_per_ip_per_hour, DEFAULT_STEPUP_EMAIL_PER_IP_PER_HOUR)
        self.assertEqual(p.sync_upload_max_bytes, DEFAULT_SYNC_UPLOAD_MAX_BYTES)
        self.assertEqual(p.tus_media_max_bytes, DEFAULT_TUS_MEDIA_MAX_BYTES)
        self.assertEqual(p.auto_update_enabled, DEFAULT_AUTO_UPDATE_ENABLED)
        self.assertEqual(p.update_poll_interval_seconds, DEFAULT_UPDATE_POLL_INTERVAL_SECONDS)
        self.assertEqual(p.update_timezone, DEFAULT_UPDATE_TIMEZONE)
        self.assertEqual(p.update_window_start_hour, DEFAULT_UPDATE_WINDOW_START_HOUR)
        self.assertEqual(p.update_window_end_hour, DEFAULT_UPDATE_WINDOW_END_HOUR)
        self.assertEqual(
            p.update_apply_cutoff_minutes_before_end,
            DEFAULT_UPDATE_APPLY_CUTOFF_MINUTES_BEFORE_END,
        )
        self.assertEqual(p.update_release_keep, DEFAULT_UPDATE_RELEASE_KEEP)
        self.assertEqual(p.update_db_backup_keep, DEFAULT_UPDATE_DB_BACKUP_KEEP)
        self.assertEqual(p.comment_max_depth, DEFAULT_COMMENT_MAX_DEPTH)

    def test_save_always_pk_1_and_invalidates_cache(self):
        get_policy()  # warm cache with defaults
        SiteSettings(pk=2, verification_enabled=False).save()
        self.assertTrue(SiteSettings.objects.filter(pk=1).exists())
        self.assertFalse(SiteSettings.objects.filter(pk=2).exists())
        self.assertFalse(get_policy().verification_enabled)

    def test_delete_is_noop(self):
        obj, _ = SiteSettings.objects.get_or_create(pk=1)
        obj.delete()
        self.assertTrue(SiteSettings.objects.filter(pk=1).exists())

    def test_invalidate_then_reread(self):
        obj, _ = SiteSettings.objects.get_or_create(pk=1)
        obj.register_per_ip_per_day = 1
        obj.save()
        self.assertEqual(get_policy().register_per_ip_per_day, 1)
        SiteSettings.objects.filter(pk=1).update(register_per_ip_per_day=9)
        # queryset.update skips Model.save → cache stale until explicit drop
        self.assertEqual(get_policy().register_per_ip_per_day, 1)
        invalidate_policy_cache()
        self.assertEqual(get_policy().register_per_ip_per_day, 9)

    def test_window_hours_reject_out_of_range(self):
        obj, _ = SiteSettings.objects.get_or_create(pk=1)
        obj.update_window_start_hour = 24
        with self.assertRaises(ValidationError):
            obj.full_clean()
        obj.update_window_start_hour = 1
        obj.update_window_end_hour = -1
        with self.assertRaises(ValidationError):
            obj.full_clean()

    def test_comment_max_depth_rejects_out_of_range(self):
        obj, _ = SiteSettings.objects.get_or_create(pk=1)
        obj.comment_max_depth = 0
        with self.assertRaises(ValidationError):
            obj.full_clean()
        obj.comment_max_depth = 33
        with self.assertRaises(ValidationError):
            obj.full_clean()
        obj.comment_max_depth = 1
        obj.full_clean()
        obj.comment_max_depth = 32
        obj.full_clean()

    def test_admin_fieldset_login_throttle(self):
        titles = [fs[0] for fs in SiteSettingsAdmin.fieldsets]
        self.assertIn("注册与限流", titles)
        rates = next(fs for fs in SiteSettingsAdmin.fieldsets if fs[0] == "注册与限流")
        self.assertEqual(
            rates[1]["fields"],
            (
                "registration_enabled",
                "register_per_ip_per_day",
                "resend_verification_per_ip_per_hour",
                "login_per_ip_per_hour",
                "login_per_username_per_hour",
                "feedback_anon_per_ip_per_day",
                "reports_per_user_per_day",
                "authcode_redeem_per_user_per_hour",
                "member_claim_enabled",
                "member_claim_per_user_per_hour",
                "member_claim_per_ip_per_day",
                "member_check_per_ip_per_hour",
                "member_lookup_per_ip_per_hour",
                "stepup_email_per_user_per_hour",
                "stepup_email_per_ip_per_hour",
            ),
        )

    def test_admin_fieldset_content_review(self):
        titles = [fs[0] for fs in SiteSettingsAdmin.fieldsets]
        self.assertIn("审核", titles)
        review = next(fs for fs in SiteSettingsAdmin.fieldsets if fs[0] == "审核")
        self.assertEqual(review[1]["fields"], ("content_review_enabled",))

    def test_admin_fieldset_comment_max_depth(self):
        titles = [fs[0] for fs in SiteSettingsAdmin.fieldsets]
        self.assertIn("评论", titles)
        comments = next(fs for fs in SiteSettingsAdmin.fieldsets if fs[0] == "评论")
        self.assertEqual(comments[1]["fields"], ("comments_enabled", "comment_max_depth"))

    def test_admin_fieldset_dms_enabled(self):
        titles = [fs[0] for fs in SiteSettingsAdmin.fieldsets]
        self.assertIn("私信", titles)
        dms = next(fs for fs in SiteSettingsAdmin.fieldsets if fs[0] == "私信")
        self.assertEqual(dms[1]["fields"], ("dms_enabled",))

    def test_admin_fieldset_auto_update(self):
        titles = [fs[0] for fs in SiteSettingsAdmin.fieldsets]
        self.assertIn("自动更新", titles)
        auto = next(fs for fs in SiteSettingsAdmin.fieldsets if fs[0] == "自动更新")
        self.assertEqual(
            auto[1]["fields"],
            (
                "auto_update_enabled",
                "update_poll_interval_seconds",
                "update_timezone",
                "update_window_start_hour",
                "update_window_end_hour",
                "update_apply_cutoff_minutes_before_end",
                "update_release_keep",
                "update_db_backup_keep",
            ),
        )


class SitePolicyPublicGetTest(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_anonymous_get_returns_snapshot(self):
        resp = APIClient().get("/site-policy/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["verification_enabled"], True)
        self.assertEqual(data["content_review_enabled"], True)
        self.assertEqual(data["registration_enabled"], True)
        self.assertEqual(data["register_per_ip_per_day"], 5)
        self.assertEqual(data["resend_verification_per_ip_per_hour"], 5)
        self.assertEqual(data["login_per_ip_per_hour"], 30)
        self.assertEqual(data["login_per_username_per_hour"], 10)
        self.assertEqual(data["feedback_anon_per_ip_per_day"], 10)
        self.assertEqual(data["reports_per_user_per_day"], 10)
        self.assertEqual(data["authcode_redeem_per_user_per_hour"], 10)
        self.assertEqual(data["sync_upload_max_bytes"], 50 * 1024 * 1024)
        self.assertEqual(data["tus_media_max_bytes"], 500 * 1024 * 1024)
        self.assertEqual(data["auto_update_enabled"], True)
        self.assertEqual(data["update_poll_interval_seconds"], 900)
        self.assertEqual(data["update_timezone"], "Asia/Shanghai")
        self.assertEqual(data["update_window_start_hour"], 1)
        self.assertEqual(data["update_window_end_hour"], 3)
        self.assertEqual(data["update_apply_cutoff_minutes_before_end"], 30)
        self.assertEqual(data["update_release_keep"], 3)
        self.assertEqual(data["update_db_backup_keep"], 5)
        self.assertEqual(data["comment_max_depth"], 8)
        self.assertEqual(data["turnstile_enabled"], False)
        self.assertEqual(data["turnstile_site_key"], "")

    @override_settings(TURNSTILE_SITE_KEY="public-sitekey", TURNSTILE_SECRET_KEY="secret")
    def test_get_overlays_turnstile_when_both_keys_set(self):
        data = APIClient().get("/site-policy/").json()
        self.assertTrue(data["turnstile_enabled"])
        self.assertEqual(data["turnstile_site_key"], "public-sitekey")
        self.assertNotIn("turnstile_secret", data)
        self.assertNotIn("TURNSTILE_SECRET_KEY", data)

    @override_settings(TURNSTILE_SITE_KEY="public-sitekey", TURNSTILE_SECRET_KEY="")
    def test_get_hides_sitekey_when_secret_missing(self):
        data = APIClient().get("/site-policy/").json()
        self.assertFalse(data["turnstile_enabled"])
        self.assertEqual(data["turnstile_site_key"], "")

    def test_get_reflects_saved_row(self):
        obj, _ = SiteSettings.objects.get_or_create(pk=1)
        obj.verification_enabled = False
        obj.content_review_enabled = False
        obj.sync_upload_max_bytes = 1024
        obj.auto_update_enabled = False
        obj.update_poll_interval_seconds = 60
        obj.update_timezone = "UTC"
        obj.update_window_start_hour = 2
        obj.update_window_end_hour = 4
        obj.update_apply_cutoff_minutes_before_end = 15
        obj.update_release_keep = 2
        obj.update_db_backup_keep = 1
        obj.save()
        data = APIClient().get("/site-policy/").json()
        self.assertFalse(data["verification_enabled"])
        self.assertFalse(data["content_review_enabled"])
        self.assertEqual(data["sync_upload_max_bytes"], 1024)
        self.assertFalse(data["auto_update_enabled"])
        self.assertEqual(data["update_poll_interval_seconds"], 60)
        self.assertEqual(data["update_timezone"], "UTC")
        self.assertEqual(data["update_window_start_hour"], 2)
        self.assertEqual(data["update_window_end_hour"], 4)
        self.assertEqual(data["update_apply_cutoff_minutes_before_end"], 15)
        self.assertEqual(data["update_release_keep"], 2)
        self.assertEqual(data["update_db_backup_keep"], 1)
