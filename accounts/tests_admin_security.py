"""管理端登录记录（P4）：只读 + 查看留痕。"""
from django.contrib.auth.models import User
from django.test import TestCase

from .models import AdminAccessLog


class AdminLoginAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root_audit", "root@example.com", "Passw0rd!2026")
        self.member = User.objects.create_user("member_a", password="Passw0rd!2026")
        self.client.force_login(self.admin)

    def test_changelist_is_readonly_and_logs_access(self):
        resp = self.client.get("/admin/accounts/loginevent/")
        self.assertEqual(resp.status_code, 200)
        log = AdminAccessLog.objects.get(scope="login_events")
        self.assertEqual(log.actor_id, self.admin.id)
        self.assertIsNone(log.target_id)

    def test_filter_by_user_records_target(self):
        resp = self.client.get(f"/admin/accounts/loginevent/?user__id__exact={self.member.id}")
        self.assertEqual(resp.status_code, 200)
        log = AdminAccessLog.objects.filter(scope="login_events").first()
        self.assertEqual(log.target_id, self.member.id)

    def test_add_is_forbidden(self):
        resp = self.client.get("/admin/accounts/loginevent/add/")
        self.assertEqual(resp.status_code, 403)

    def test_devices_changelist_logs_scope(self):
        resp = self.client.get("/admin/accounts/accountdevice/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AdminAccessLog.objects.filter(scope="devices", actor=self.admin).exists())

    def test_member_cannot_open_admin(self):
        self.client.force_login(self.member)
        resp = self.client.get("/admin/accounts/loginevent/")
        self.assertIn(resp.status_code, (302, 403))
