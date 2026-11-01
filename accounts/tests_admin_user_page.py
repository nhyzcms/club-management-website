"""用户管理页回归：B4 拆表之后，用户详情页不能再引用 Profile 上已删的列。

事故（2026-11-01 生产）：``ProfileInline.get_readonly_fields()`` 仍返回
``expiry_disabled_at`` / ``deleted_at`` / ``validity_notice_ack`` /
``registration_deadline``。这四列已在 B4（``0035_drop_profile_legacy_columns``）
从 ``Profile`` 删除，Django 解析 readonly 字段名时抛
``AttributeError: Unable to lookup 'expiry_disabled_at' on Profile ...``，
于是「用户表点进任何一个用户」和「增加用户」都整页 500——列表页正常，
所以只在详情页暴露。

**为什么 system check 没拦住**：Django 的 ``admin.E035`` 只静态检查
``readonly_fields`` 属性本身；这里是 ``get_readonly_fields()`` 运行时返回的列表，
check 看不见。唯一能拦住它的守卫是「真的 GET 一次」。
"""
from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.test import RequestFactory, TestCase

from accounts.admin import AccountLifecycleInline, CustomUserAdmin

from .testing import make_profile


def _request_for(user):
    request = RequestFactory().get("/admin/auth/user/")
    request.user = user
    return request


class UserAdminPageRendersTest(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser("page-root", "root@example.com", "pw-root-123")
        self.member = User.objects.create_user(username="page-member", password="pw-member-123")
        make_profile(
            self.member,
            real_name="张三",
            identity="student",
            card_no="20260101",
            registration_deadline=None,
        )
        self.client.force_login(self.root)

    def test_user_change_page_renders(self):
        """点进用户详情页必须 200（事故现场：500 AttributeError）。"""
        resp = self.client.get(f"/admin/auth/user/{self.member.pk}/change/")
        self.assertEqual(resp.status_code, 200)

    def test_user_add_page_renders(self):
        """「增加用户」同一组 inline，同样必须 200。"""
        resp = self.client.get("/admin/auth/user/add/")
        self.assertEqual(resp.status_code, 200)

    def test_change_page_shows_split_tables(self):
        """拆表后的实名 / 生命周期信息仍在详情页可见（不是被一删了之）。"""
        resp = self.client.get(f"/admin/auth/user/{self.member.pk}/change/")
        body = resp.content.decode()
        self.assertIn("实名资料", body)
        self.assertIn("账号生命周期", body)
        self.assertIn("张三", body)
        self.assertIn("注册认证截止", body)


class LifecycleInlinePermissionTest(TestCase):
    """``registration_deadline`` 的可编辑口径沿用 ADR-0041（manage_validity + 下位）。"""

    def setUp(self):
        self.inline = AccountLifecycleInline(User, admin.site)
        self.root = User.objects.create_superuser("perm-root", "r@example.com", "pw-root-123")
        self.manager = User.objects.create_user(
            username="perm-manager", password="pw-mgr-123", is_staff=True
        )
        self.manager.user_permissions.add(
            Permission.objects.get(codename="manage_validity")
        )
        self.member = User.objects.create_user(username="perm-member", password="pw-member-123")
        make_profile(self.member)

    def test_system_fields_always_readonly(self):
        readonly = self.inline.get_readonly_fields(_request_for(self.root), self.member)
        for name in ("expiry_disabled_at", "deleted_at", "validity_notice_ack", "must_change_password"):
            self.assertIn(name, readonly)

    def test_manage_validity_can_edit_deadline_for_lower_rank(self):
        manager = User.objects.get(pk=self.manager.pk)  # 刷新权限缓存
        readonly = self.inline.get_readonly_fields(_request_for(manager), self.member)
        self.assertNotIn("registration_deadline", readonly)

    def test_plain_staff_cannot_edit_deadline(self):
        plain = User.objects.create_user(username="perm-plain", password="pw-plain-123", is_staff=True)
        readonly = self.inline.get_readonly_fields(_request_for(plain), self.member)
        self.assertIn("registration_deadline", readonly)

    def test_registered_inlines_cover_user_page(self):
        names = [inline.__name__ for inline in CustomUserAdmin(User, admin.site).inlines]
        self.assertIn("ProfileInline", names)
        self.assertIn("AccountLifecycleInline", names)
