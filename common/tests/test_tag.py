"""Tag 归位到 common 的回归（B7）。

搬家的风险不在代码，在**权限**：模型 app_label 从 ``tasks`` 变成 ``common``，
权限 codename 随之变成 ``common.manage_tags``。旧的授予不会自动跟过来，
症状是「标签页能看、一保存就 403」——静默、且只在生产暴露。

这里钉住三件事：
1. 物理表名没变（``tasks_tag``，零 DDL 的前提）；
2. 权限行落在 ``common`` 下；
3. 判定读的是 ``common.manage_tags``（不是 ``tasks.manage_tags``）。
"""
from django.contrib.auth.models import Permission, User
from django.test import RequestFactory, TestCase

from common.models import Tag
from tasks.permissions import CanManageTag


class TagModelLocationTest(TestCase):
    def test_table_name_unchanged(self):
        """零 DDL 的前提：搬家后表名必须还是 tasks_tag。"""
        self.assertEqual(Tag._meta.db_table, "tasks_tag")

    def test_app_label_is_common(self):
        self.assertEqual(Tag._meta.app_label, "common")

    def test_permission_declared_on_common(self):
        self.assertIn(("manage_tags", "可管理标签"), Tag._meta.permissions)

    def test_manage_tags_permission_row_exists_under_common(self):
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="common", codename="manage_tags",
            ).exists(),
            "common.manage_tags 权限行不存在——迁移后 post_migrate 应当建出来",
        )


class CanManageTagTest(TestCase):
    """写权限必须读 common.manage_tags。

    旧实现读 ``tasks.manage_tags``。那条权限行仍然存在（迁移刻意保留以支持回滚），
    所以**如果代码没改干净，测试依然会绿**——这也是本测试要显式授
    ``common.manage_tags`` 而不是随便给个权限的原因。
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="tagmgr", password="x")

    def _req(self, method, user=None):
        req = getattr(self.factory, method)("/tasks/tags/")
        req.user = user or self.user
        return req

    def test_safe_method_allows_any_logged_in(self):
        self.assertTrue(CanManageTag().has_permission(self._req("get"), None))

    def test_write_denied_without_permission(self):
        self.assertFalse(CanManageTag().has_permission(self._req("post"), None))

    def test_write_allowed_with_common_permission(self):
        perm = Permission.objects.get(
            content_type__app_label="common", codename="manage_tags",
        )
        self.user.user_permissions.add(perm)
        fresh = User.objects.get(pk=self.user.pk)  # 清掉权限缓存
        self.assertTrue(CanManageTag().has_permission(self._req("post", fresh), None))

    def test_tasks_side_permission_no_longer_grants(self):
        """旧 codename 不该再放行——否则「搬完了但判定没改」会被漏掉。"""
        old = Permission.objects.filter(
            content_type__app_label="tasks", codename="manage_tags",
        ).first()
        if old is None:
            self.skipTest("旧权限行不存在（未来若清理了，这条自然失去意义）")
        self.user.user_permissions.add(old)
        fresh = User.objects.get(pk=self.user.pk)
        self.assertFalse(CanManageTag().has_permission(self._req("post", fresh), None))
