"""公开站点策略快照的字段契约（审计 #274）。

这个文件的目的是让「不小心公开一个新字段」变成测试红，而不是发布后靠人回想。
新增任何公开字段：改 ``common/views.PUBLIC_POLICY_FIELDS`` + 这里的冻结集合 +
前端 ``api/sitePolicy.ts`` 的 interface（三处必须同时动）。
"""
from types import SimpleNamespace

from django.test import TestCase
from rest_framework.test import APIClient

from common.policy import SitePolicy
from common.views import PUBLIC_POLICY_FIELDS, public_policy_snapshot

#: 冻结清单：匿名可读的全部键（含 Turnstile 两字段）。
PUBLIC_KEYS = {
    "verification_enabled",
    "verification_valid_days",
    "admin_valid_days",
    "registration_verify_days",
    "registration_enabled",
    "comments_enabled",
    "comment_max_depth",
    "dms_enabled",
    "sync_upload_max_bytes",
    "turnstile_enabled",
    "turnstile_site_key",
}


class PublicPolicySnapshotTest(TestCase):
    def test_endpoint_exposes_exactly_the_allowlist(self):
        resp = APIClient().get("/site-policy/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.data), PUBLIC_KEYS)

    def test_operational_knobs_not_exposed(self):
        """运维参数（更新窗口、tus 上限、各条限流阈值）不再匿名可读。"""
        data = APIClient().get("/site-policy/").data
        for leaked in (
            "update_window_start_hour",
            "update_window_end_hour",
            "auto_update_enabled",
            "update_timezone",
            "update_poll_interval_seconds",
            "update_release_keep",
            "update_db_backup_keep",
            "tus_media_max_bytes",
            "login_per_ip_per_hour",
            "login_per_username_per_hour",
            "register_per_ip_per_day",
            "reports_per_user_per_day",
            "feedback_anon_per_ip_per_day",
            "resend_verification_per_ip_per_hour",
            "authcode_redeem_per_user_per_hour",
            "member_lookup_per_ip_per_hour",
            "member_check_per_ip_per_hour",
            "stepup_email_per_ip_per_hour",
            # 前端没有消费端：不公开
            "content_review_enabled",
        ):
            self.assertNotIn(leaked, data, f"{leaked} 不应出现在公开快照里")

    def test_new_policy_field_does_not_auto_publish(self):
        """``asdict`` 换成 allowlist 的核心收益：新字段默认不公开。"""
        defaults = SitePolicy.defaults()
        fake = SimpleNamespace(
            **{name: getattr(defaults, name) for name in PUBLIC_POLICY_FIELDS}
        )
        fake.secret_internal_knob = 42
        snap = public_policy_snapshot(fake)
        self.assertNotIn("secret_internal_knob", snap)
        self.assertEqual(set(snap), set(PUBLIC_POLICY_FIELDS))

    def test_allowlist_is_frozen(self):
        """字段集合本身冻结——扩公开面必须是一次显式改动。"""
        self.assertEqual(
            set(PUBLIC_POLICY_FIELDS),
            PUBLIC_KEYS - {"turnstile_enabled", "turnstile_site_key"},
        )
