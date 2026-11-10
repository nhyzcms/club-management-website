"""MaintenanceModeMiddleware: file flag → 503 HTML, no DB, no SPA."""
import copy
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from common.maintenance import (
    REASON_OPS,
    REASON_UPDATE,
    enter_ops,
    enter_update,
    leave_ops,
    read_status,
    update_progress,
)
from common.middleware import MAINTENANCE_FLAG_PATH

SPA_MOUNT = 'id="root"'
MAINTENANCE_HEADING = "系统维护中"
UPDATE_HEADING = "系统更新中"


class _FlagMixin:
    """Save / restore the real run/MAINTENANCE flag around each test."""

    def setUp(self):
        super().setUp()
        self._flag_existed = MAINTENANCE_FLAG_PATH.exists()
        self._flag_bytes = (
            MAINTENANCE_FLAG_PATH.read_bytes() if self._flag_existed else None
        )
        self.addCleanup(self._restore_flag)

    def _restore_flag(self):
        if self._flag_bytes is not None:
            MAINTENANCE_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
            MAINTENANCE_FLAG_PATH.write_bytes(self._flag_bytes)
        elif MAINTENANCE_FLAG_PATH.exists():
            MAINTENANCE_FLAG_PATH.unlink()

    def _flag_on(self):
        MAINTENANCE_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        MAINTENANCE_FLAG_PATH.write_text("", encoding="utf-8")

    def _flag_off(self):
        if MAINTENANCE_FLAG_PATH.exists():
            MAINTENANCE_FLAG_PATH.unlink()


class MaintenanceFlagOnTest(_FlagMixin, SimpleTestCase):
    """Flag present → 503 maintenance HTML. SimpleTestCase forbids DB access."""

    def test_flag_path_is_under_base_dir_run(self):
        self.assertEqual(
            MAINTENANCE_FLAG_PATH,
            Path(settings.BASE_DIR) / "run" / "MAINTENANCE",
        )

    def test_home_returns_503_html_not_spa(self):
        self._flag_on()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 503)
        body = resp.content.decode()
        self.assertIn(MAINTENANCE_HEADING, body)
        self.assertNotIn(SPA_MOUNT, body)
        self.assertEqual(resp["Cache-Control"], "no-store")

    def test_index_catch_all_returns_503_not_spa(self):
        self._flag_on()
        resp = self.client.get("/login/")
        self.assertEqual(resp.status_code, 503)
        body = resp.content.decode()
        self.assertIn(MAINTENANCE_HEADING, body)
        self.assertNotIn(SPA_MOUNT, body)

    def test_admin_also_intercepted(self):
        self._flag_on()
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 503)

    def test_ops_message_on_page(self):
        enter_ops(MAINTENANCE_FLAG_PATH, "磁盘扩容")
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 503)
        body = resp.content.decode()
        self.assertIn(MAINTENANCE_HEADING, body)
        self.assertIn("磁盘扩容", body)
        self.assertNotIn('http-equiv="refresh"', body)

    def test_update_progress_refreshes_and_shows_bar(self):
        enter_update(MAINTENANCE_FLAG_PATH, sha="abcdef1234567890")
        update_progress(MAINTENANCE_FLAG_PATH, "migrate", sha="abcdef1234567890")
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 503)
        body = resp.content.decode()
        self.assertIn(UPDATE_HEADING, body)
        self.assertIn("正在迁移数据库", body)
        self.assertIn('http-equiv="refresh"', body)
        self.assertIn("6 / 8", body)
        self.assertIn("abcdef123456", body)
        self.assertEqual(resp["Retry-After"], "5")


class MaintenanceFlagOffTest(_FlagMixin, TestCase):
    """No flag → home / index still render the SPA shell (index.html)."""

    def setUp(self):
        super().setUp()
        self._flag_off()
        self._tmpl_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self._tmpl_dir, ignore_errors=True))
        (self._tmpl_dir / "index.html").write_text(
            '<!DOCTYPE html><html><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )
        templates = copy.deepcopy(settings.TEMPLATES)
        templates[0]["DIRS"] = [str(self._tmpl_dir), *templates[0]["DIRS"]]
        self._settings_cm = self.settings(TEMPLATES=templates)
        self._settings_cm.enable()
        self.addCleanup(self._settings_cm.disable)

    def test_home_serves_spa_not_maintenance(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "index.html")
        self.assertTemplateNotUsed(resp, "maintenance.html")
        body = resp.content.decode()
        self.assertIn(SPA_MOUNT, body)
        self.assertNotIn(MAINTENANCE_HEADING, body)

    def test_index_catch_all_serves_spa_not_maintenance(self):
        resp = self.client.get("/login/")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "index.html")
        self.assertTemplateNotUsed(resp, "maintenance.html")
        body = resp.content.decode()
        self.assertIn(SPA_MOUNT, body)
        self.assertNotIn(MAINTENANCE_HEADING, body)


class MaintenanceStaticFallbackTest(SimpleTestCase):
    """Nginx 502 fallback is a generic page; live progress is Django-rendered."""

    def test_static_copy_is_generic_fallback(self):
        static = Path(settings.BASE_DIR) / "static" / "maintenance.html"
        text = static.read_text(encoding="utf-8")
        self.assertIn(MAINTENANCE_HEADING, text)
        self.assertNotIn("{{", text)
        self.assertIn("服务正在重载", text)


class MaintenanceCommandAndResumeTest(_FlagMixin, SimpleTestCase):
    def test_command_on_off_status(self):
        self._flag_off()
        call_command("maintenance", "on", "--message", "搬家")
        status = read_status(MAINTENANCE_FLAG_PATH)
        self.assertIsNotNone(status)
        self.assertEqual(status.reason, REASON_OPS)
        self.assertEqual(status.message, "搬家")
        call_command("maintenance", "off")
        self.assertIsNone(read_status(MAINTENANCE_FLAG_PATH))

    def test_ops_during_update_resumes_after_leave_update(self):
        from common.maintenance import leave_update

        enter_ops(MAINTENANCE_FLAG_PATH, "人工维护")
        enter_update(MAINTENANCE_FLAG_PATH, sha="aa")
        status = read_status(MAINTENANCE_FLAG_PATH)
        self.assertEqual(status.reason, REASON_UPDATE)
        self.assertTrue(status.resume_ops)
        leave_update(MAINTENANCE_FLAG_PATH)
        status = read_status(MAINTENANCE_FLAG_PATH)
        self.assertEqual(status.reason, REASON_OPS)
        self.assertEqual(status.message, "人工维护")
        leave_ops(MAINTENANCE_FLAG_PATH)
        self.assertIsNone(read_status(MAINTENANCE_FLAG_PATH))
