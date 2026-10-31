"""策略表：默认值、缓存失效、单例语义、字段归属、公开 GET。

## B5 之后的变化

`SiteSettings` 一张表拆成五张（Auth / RateLimit / Upload / Updater / Content）。
`get_policy()` 仍返回同一个 `SitePolicy` dataclass，所以这里**默认值断言一字未改**
——那部分测的是「契约」，契约没动。

改的是「怎么造前置条件」和「字段归属」：
- 造数据用 `set_policy(**fields)`（按字段名找表）
- admin 断言从「一个 33 字段的 fieldsets」变成「每张表只装本领域的字段」
"""
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from common.admin import (
    AuthPolicyAdmin,
    ContentPolicyAdmin,
    RateLimitPolicyAdmin,
    UpdaterPolicyAdmin,
    UploadPolicyAdmin,
)
from common.models import (
    AuthPolicy,
    ContentPolicy,
    RateLimitPolicy,
    UpdaterPolicy,
    UploadPolicy,
)
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
from common.testing import set_policy

POLICY_MODELS = (AuthPolicy, ContentPolicy, RateLimitPolicy, UpdaterPolicy, UploadPolicy)


class SitePolicyDefaultsTest(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_missing_row_returns_today_hardcoded_defaults(self):
        for model in POLICY_MODELS:
            self.assertFalse(model.objects.exists(), f"{model.__name__} 不该有行")
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

    def test_each_policy_table_is_singleton(self):
        """五张表各自 pk 恒为 1，保存后清缓存。"""
        get_policy()  # 预热缓存
        AuthPolicy(pk=2, verification_enabled=False).save()
        self.assertTrue(AuthPolicy.objects.filter(pk=1).exists())
        self.assertFalse(AuthPolicy.objects.filter(pk=2).exists())
        self.assertFalse(get_policy().verification_enabled)

    def test_delete_is_noop(self):
        row, _ = UpdaterPolicy.objects.get_or_create(pk=1)
        row.delete()
        self.assertTrue(UpdaterPolicy.objects.filter(pk=1).exists())

    def test_invalidate_then_reread(self):
        set_policy(register_per_ip_per_day=1)
        self.assertEqual(get_policy().register_per_ip_per_day, 1)
        # queryset.update 绕过 Model.save → 缓存直到显式失效才更新
        RateLimitPolicy.objects.filter(pk=1).update(register_per_ip_per_day=9)
        self.assertEqual(get_policy().register_per_ip_per_day, 1)
        invalidate_policy_cache()
        self.assertEqual(get_policy().register_per_ip_per_day, 9)

    def test_partial_tables_fall_back_per_field(self):
        """只配了频控、没配上传：频控生效，上传仍是默认。

        这是拆分带来的新语义——旧的单表实现里「有行」意味着「所有字段都有值」，
        拆开后每张表独立，缺行只影响本领域。
        """
        set_policy(login_per_ip_per_hour=3)
        p = get_policy()
        self.assertEqual(p.login_per_ip_per_hour, 3)
        self.assertEqual(p.tus_media_max_bytes, DEFAULT_TUS_MEDIA_MAX_BYTES)
        self.assertEqual(p.update_timezone, DEFAULT_UPDATE_TIMEZONE)

    def test_window_hours_reject_out_of_range(self):
        row, _ = UpdaterPolicy.objects.get_or_create(pk=1)
        row.update_window_start_hour = 24
        with self.assertRaises(ValidationError):
            row.full_clean()
        row.update_window_start_hour = 1
        row.update_window_end_hour = -1
        with self.assertRaises(ValidationError):
            row.full_clean()

    def test_comment_max_depth_rejects_out_of_range(self):
        row, _ = ContentPolicy.objects.get_or_create(pk=1)
        row.comment_max_depth = 0
        with self.assertRaises(ValidationError):
            row.full_clean()
        row.comment_max_depth = 33
        with self.assertRaises(ValidationError):
            row.full_clean()
        row.comment_max_depth = 1
        row.full_clean()
        row.comment_max_depth = 32
        row.full_clean()


class PolicyFieldOwnershipTest(TestCase):
    """字段归属：每张表只装本领域的字段。

    这是拆分的主要收益——改上传上限不再连带 33 个字段一起提交。断言「别人的字段
    不在这里」比断言「我的字段在这里」更能守住边界。
    """

    @staticmethod
    def _names(model):
        return {f.name for f in model._meta.get_fields()}

    def test_auth_policy_owns_verification_and_registration(self):
        names = self._names(AuthPolicy)
        for f in (
            "verification_enabled", "verification_valid_days", "admin_valid_days",
            "registration_verify_days", "registration_enabled", "member_claim_enabled",
        ):
            self.assertIn(f, names)
        self.assertNotIn("login_per_ip_per_hour", names)
        self.assertNotIn("auto_update_enabled", names)

    def test_rate_limit_policy_owns_all_throttles(self):
        names = self._names(RateLimitPolicy)
        self.assertIn("login_per_ip_per_hour", names)
        self.assertIn("member_lookup_per_ip_per_hour", names)
        self.assertNotIn("verification_enabled", names)
        self.assertNotIn("sync_upload_max_bytes", names)

    def test_upload_policy_is_only_two_caps(self):
        names = self._names(UploadPolicy) - {"id"}
        self.assertEqual(names, {"sync_upload_max_bytes", "tus_media_max_bytes"})

    def test_updater_policy_owns_update_knobs(self):
        names = self._names(UpdaterPolicy)
        for f in (
            "auto_update_enabled", "update_poll_interval_seconds", "update_timezone",
            "update_window_start_hour", "update_window_end_hour",
            "update_apply_cutoff_minutes_before_end", "update_release_keep",
            "update_db_backup_keep",
        ):
            self.assertIn(f, names)
        self.assertNotIn("comment_max_depth", names)

    def test_content_policy_owns_review_and_comments(self):
        names = self._names(ContentPolicy)
        for f in ("content_review_enabled", "comments_enabled", "comment_max_depth", "dms_enabled"):
            self.assertIn(f, names)
        self.assertNotIn("registration_enabled", names)

    def test_all_thirty_three_fields_are_covered_once(self):
        """33 个字段一个不落、也不重复。漏一个会让它悄悄回到默认值。"""
        seen = []
        for model in POLICY_MODELS:
            for f in model._meta.get_fields():
                if f.concrete and not f.auto_created and f.name != "id":
                    seen.append(f.name)
        self.assertEqual(len(seen), 33, f"实际 {len(seen)} 个：{sorted(seen)}")
        self.assertEqual(len(set(seen)), 33, "有字段被放进了两张表")


class PolicyAdminTest(TestCase):
    """五张表的 admin 都是「只有一行、不能增删」。"""

    ADMINS = (
        (AuthPolicyAdmin, AuthPolicy),
        (RateLimitPolicyAdmin, RateLimitPolicy),
        (UploadPolicyAdmin, UploadPolicy),
        (UpdaterPolicyAdmin, UpdaterPolicy),
        (ContentPolicyAdmin, ContentPolicy),
    )

    def test_cannot_add_or_delete(self):
        from django.contrib.admin.sites import site

        for admin_cls, model in self.ADMINS:
            instance = admin_cls(model, site)
            self.assertFalse(instance.has_add_permission(request=None))
            self.assertFalse(instance.has_delete_permission(request=None))

    def test_changelist_redirects_to_the_single_row(self):
        from django.contrib.admin.sites import site

        for admin_cls, model in self.ADMINS:
            instance = admin_cls(model, site)
            resp = instance.changelist_view(request=None)
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(model.objects.filter(pk=1).exists())


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
        """跨五张表一起改，公开端点要一次性反映出来。"""
        set_policy(
            verification_enabled=False,
            content_review_enabled=False,
            sync_upload_max_bytes=1024,
            auto_update_enabled=False,
            update_poll_interval_seconds=60,
            update_timezone="UTC",
            update_window_start_hour=2,
            update_window_end_hour=4,
            update_apply_cutoff_minutes_before_end=15,
            update_release_keep=2,
            update_db_backup_keep=1,
        )
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
