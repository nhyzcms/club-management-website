from django.contrib.auth.models import Group, Permission, User
from django.db.models import Q
from django.test import TestCase

from reviews.visibility import public_q

from .visibility import (
    ContentVisibility,
    ProfileVisibility,
    content_visibility,
    is_admin_viewer,
    profile_view_for,
)


def _grant(user, app_label, codename):
    """直接授予某权限（不经组），并刷新实例以清权限缓存。"""
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label=app_label, codename=codename)
    )
    return User.objects.get(pk=user.pk)


# ---- 管理员判定：权限而非硬编码「信息组」组名（#8 故事 7-8）----


class IsAdminViewerTest(TestCase):
    def setUp(self):
        self.regular = User.objects.create_user(username="regular", password="p")
        # 直接授予权限（不在「信息组」组里）—— 钉死「权限即管理员」
        self.direct = _grant(User.objects.create_user(username="direct", password="p"), "news", "manage_news")
        # 经「信息组」组获得权限（组仍生效，因其授予该权限）
        info = User.objects.create_user(username="info", password="p")
        info.groups.add(Group.objects.get_or_create(name="信息组")[0])
        self.in_info_group = User.objects.get(pk=info.pk)
        # 在某组但该组不授 news.manage_news —— 钉死「组名本身不算数」
        other = User.objects.create_user(username="other_grp", password="p")
        other.groups.add(Group.objects.create(name="noop_group"))
        self.in_other_group = User.objects.get(pk=other.pk)
        self.superuser = User.objects.create_superuser(username="root", email="r@e.com", password="p")

    def test_superuser_is_admin(self):
        self.assertTrue(is_admin_viewer(self.superuser))

    def test_direct_permission_is_admin(self):
        # 授予 news.manage_news（不在信息组）→ 仍是管理员
        self.assertTrue(is_admin_viewer(self.direct))

    def test_info_group_member_is_admin(self):
        # 信息组成员（经组获得 news.manage_news）→ 管理员
        self.assertTrue(is_admin_viewer(self.in_info_group))

    def test_regular_is_not_admin(self):
        self.assertFalse(is_admin_viewer(self.regular))

    def test_group_without_permission_is_not_admin(self):
        # 关键钉死：仅在某组（无 news.manage_news）不算管理员
        self.assertFalse(is_admin_viewer(self.in_other_group))


# ---- 资料字段可见性矩阵（#8 故事 1-6）----


class ProfileViewForTest(TestCase):
    def setUp(self):
        self.viewed = User.objects.create_user(username="viewed", email="v@e.com", password="p")
        self.other = User.objects.create_user(username="other", password="p")
        self.admin = _grant(
            User.objects.create_user(username="admin", password="p"), "news", "manage_news"
        )
        self.inactive = User.objects.create_user(username="inactive", password="p", is_active=False)

    def test_owner_sees_private_and_sensitive(self):
        v = profile_view_for(self.viewed, self.viewed)
        self.assertIsInstance(v, ProfileVisibility)
        self.assertTrue(v.is_owner)
        self.assertFalse(v.is_admin)
        self.assertTrue(v.can_see_private)     # email / birthday / gender
        self.assertTrue(v.can_see_sensitive)   # permissions / groups

    def test_admin_sees_sensitive_but_not_private(self):
        v = profile_view_for(self.admin, self.viewed)
        self.assertFalse(v.is_owner)
        self.assertTrue(v.is_admin)
        self.assertFalse(v.can_see_private)
        self.assertTrue(v.can_see_sensitive)

    def test_regular_other_sees_neither(self):
        v = profile_view_for(self.other, self.viewed)
        self.assertFalse(v.is_owner)
        self.assertFalse(v.is_admin)
        self.assertFalse(v.can_see_private)
        self.assertFalse(v.can_see_sensitive)

    def test_module_is_inactive_agnostic(self):
        # 模块不按 is_active 裁剪（停用→404 的边界在视图层）；裁定与正常用户一致。
        v = profile_view_for(self.other, self.inactive)
        self.assertFalse(v.is_owner)
        self.assertFalse(v.can_see_private)


# ---- 内容可见性矩阵（#8 故事 9-14）----


class ContentVisibilityTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="p")
        self.other = User.objects.create_user(username="other", password="p")

    def test_news_owner_sees_all(self):
        self.assertEqual(
            content_visibility(self.owner, self.owner, "news"),
            ContentVisibility(denied=False, extra_q=Q()),
        )

    def _pks(self, queryset):
        return sorted(queryset.values_list("pk", flat=True))

    def test_news_other_only_published(self):
        """他人看新闻：只看到「已发布 **且** 过审」的。

        B9 之后 ``public_q`` 返回的是 ``Q(pk__in=<子查询>)``，两次调用拿到的是两个
        不同的子查询实例，而 Django 的 ``Q.__eq__`` 比的是子查询对象本身——所以
        不能再断言「Q 相等」。这里比**结果集**，并且额外钉死具体是哪一条，
        避免两个都错成空集也算通过。
        """
        from common.targets import target_of
        from news.models import News
        from reviews.models import Review

        published_ok = News.objects.create(title="ok", author=self.owner, is_published=True)
        Review.objects.create(target=target_of(published_ok), status=Review.STATUS_APPROVED)

        published_pending = News.objects.create(title="pending", author=self.owner, is_published=True)
        Review.objects.create(target=target_of(published_pending), status=Review.STATUS_PENDING)

        draft_ok = News.objects.create(title="draft", author=self.owner, is_published=False)
        Review.objects.create(target=target_of(draft_ok), status=Review.STATUS_APPROVED)

        vis = content_visibility(self.other, self.owner, "news")
        self.assertFalse(vis.denied)
        got = self._pks(News.objects.filter(vis.extra_q))
        want = self._pks(News.objects.filter(public_q("news") & Q(is_published=True)))
        self.assertEqual(got, want)
        self.assertEqual(got, [published_ok.pk])

    def test_feedback_owner_sees_all(self):
        self.assertEqual(
            content_visibility(self.owner, self.owner, "feedback"),
            ContentVisibility(denied=False, extra_q=Q()),
        )

    def test_feedback_other_sees_none(self):
        self.assertEqual(
            content_visibility(self.other, self.owner, "feedback"),
            ContentVisibility(denied=False, extra_q=Q(pk__in=[])),
        )

    def test_tasks_owner_ok(self):
        self.assertEqual(
            content_visibility(self.owner, self.owner, "tasks"),
            ContentVisibility(denied=False, extra_q=Q()),
        )

    def test_tasks_other_denied(self):
        # 任务仅本人；他人无权（视图据此 403）
        self.assertEqual(
            content_visibility(self.other, self.owner, "tasks"),
            ContentVisibility(denied=True, extra_q=Q()),
        )

    def test_activities_owner_sees_all(self):
        self.assertEqual(
            content_visibility(self.owner, self.owner, "activities"),
            ContentVisibility(denied=False, extra_q=Q()),
        )

    def test_activities_other_extra_q_matches_public_q(self):
        """他人看活动：过审的 + 从来没有审核行的（存量例外）。

        B9 之后 ``public_q`` 是子查询，两个结构相同的 Q 不再相等，所以比结果集。
        """
        from activities.models import Activity
        from common.targets import target_of
        from reviews.models import Review

        approved = Activity.objects.create(
            type="deliberation", status="open", title="approved", creator=self.owner,
        )
        Review.objects.create(target=target_of(approved), status=Review.STATUS_APPROVED)

        pending = Activity.objects.create(
            type="deliberation", status="open", title="pending", creator=self.owner,
        )
        Review.objects.create(target=target_of(pending), status=Review.STATUS_PENDING)

        never_reviewed = Activity.objects.create(
            type="deliberation", status="open", title="bare", creator=self.owner,
        )

        vis = content_visibility(self.other, self.owner, "activities")
        self.assertFalse(vis.denied)
        got = self._pks(Activity.objects.filter(vis.extra_q))
        want = self._pks(Activity.objects.filter(public_q("activity")))
        self.assertEqual(got, want)
        self.assertEqual(got, sorted([approved.pk, never_reviewed.pk]))

    def test_tutorials_owner_sees_all(self):
        self.assertEqual(
            content_visibility(self.owner, self.owner, "tutorials"),
            ContentVisibility(denied=False, extra_q=Q()),
        )

    def test_tutorials_other_extra_q_matches_public_q(self):
        """他人看教程：只看到过审的（无审核行不公开）。"""
        from common.targets import target_of
        from reviews.models import Review
        from tutorials.models import Tutorial

        approved = Tutorial.objects.create(title="approved", uploader=self.owner)
        Review.objects.create(target=target_of(approved), status=Review.STATUS_APPROVED)

        pending = Tutorial.objects.create(title="pending", uploader=self.owner)
        Review.objects.create(target=target_of(pending), status=Review.STATUS_PENDING)

        bare = Tutorial.objects.create(title="bare", uploader=self.owner)

        vis = content_visibility(self.other, self.owner, "tutorials")
        self.assertFalse(vis.denied)
        got = self._pks(Tutorial.objects.filter(vis.extra_q))
        want = self._pks(Tutorial.objects.filter(public_q("tutorial")))
        self.assertEqual(got, want)
        self.assertEqual(got, [approved.pk])

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            content_visibility(self.other, self.owner, "bogus")
