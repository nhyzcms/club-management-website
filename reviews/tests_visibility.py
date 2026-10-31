"""审核读接口单元测试（reviews.visibility）。

HTTP 作者预览仍由 tests.py / tests_activity.py / tutorials 覆盖；此处钉接口本身：
owner_id 推断、活动夹具例外、visible_queryset 三档。
"""
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from common.targets import target_of
from activities.models import Activity
from news.models import News
from reviews.models import Review
from reviews.visibility import (
    comment_for,
    owner_id,
    public_q,
    status_of,
    visible_queryset,
)
from tutorials.models import Tutorial


def _grant_moderate(user):
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="reviews", codename="moderate")
    )
    return User.objects.get(pk=user.pk)


def _tutorial(user, title="教程"):
    return Tutorial.objects.create(
        title=title,
        file=SimpleUploadedFile("a.mp4", b"x", content_type="video/mp4"),
        file_type="video",
        file_name="a.mp4",
        file_size=1,
        uploader=user,
    )


class OwnerIdTest(TestCase):
    """B9 之后 ``related_name()`` 不存在了——审核行只通过 ContentTarget 锚定，
    宿主侧没有反向访问器。这里只测 ``owner_id``（它和审核轴无关，仍需要）。"""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="x")

    def test_news_author(self):
        news = News(title="n", author=self.user)
        self.assertEqual(owner_id(news), self.user.pk)

    def test_activity_creator(self):
        activity = Activity(type="deliberation", status="open", title="a", creator=self.user)
        self.assertEqual(owner_id(activity), self.user.pk)

    def test_tutorial_uploader(self):
        tutorial = Tutorial(title="t", uploader=self.user)
        self.assertEqual(owner_id(tutorial), self.user.pk)

    def test_unknown_model_raises(self):
        with self.assertRaises(TypeError):
            owner_id(self.user)


class PublicQTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="x")

    def test_activity_isnull_fixture_is_public(self):
        orphan = Activity.objects.create(
            type="deliberation", status="open", title="fixture", creator=self.user,
        )
        self.assertTrue(
            Activity.objects.filter(public_q("activity"), pk=orphan.pk).exists()
        )

    def test_activity_pending_review_is_not_public(self):
        pending = Activity.objects.create(
            type="deliberation", status="open", title="pending", creator=self.user,
        )
        Review.objects.create(target=target_of(pending), status=Review.STATUS_PENDING)
        self.assertFalse(
            Activity.objects.filter(public_q("activity"), pk=pending.pk).exists()
        )

    def test_activity_approved_is_public(self):
        approved = Activity.objects.create(
            type="deliberation", status="open", title="ok", creator=self.user,
        )
        Review.objects.create(target=target_of(approved), status=Review.STATUS_APPROVED)
        self.assertTrue(
            Activity.objects.filter(public_q("activity"), pk=approved.pk).exists()
        )

    def test_news_orphan_without_review_is_not_public(self):
        orphan = News.objects.create(title="orphan", author=self.user, is_published=True)
        self.assertFalse(
            News.objects.filter(public_q("news"), pk=orphan.pk).exists()
        )

    def test_news_approved_is_public_even_if_unpublished(self):
        # is_published 由新闻适配器相交，审核轴本身不过问
        news = News.objects.create(title="draft", author=self.user, is_published=False)
        Review.objects.create(target=target_of(news), status=Review.STATUS_APPROVED)
        self.assertTrue(
            News.objects.filter(public_q("news"), pk=news.pk).exists()
        )

    def test_tutorial_orphan_without_review_is_not_public(self):
        orphan = _tutorial(self.user, "orphan")
        self.assertFalse(
            Tutorial.objects.filter(public_q("tutorial"), pk=orphan.pk).exists()
        )

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            public_q("bogus")


class StatusAndCommentTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="x")
        self.other = User.objects.create_user(username="other", password="x")
        self.mod = _grant_moderate(User.objects.create_user(username="mod", password="x"))
        self.news = News.objects.create(title="n", author=self.owner, is_published=True)
        Review.objects.create(target=target_of(self.news), status=Review.STATUS_REJECTED, moderation_note="改标题",
        )
        self.activity = Activity.objects.create(
            type="deliberation", status="open", title="a", creator=self.owner,
        )
        Review.objects.create(target=target_of(self.activity), status=Review.STATUS_PENDING, moderation_note="活动评语",
        )

    def test_status_of_infers_related_name(self):
        self.assertEqual(status_of(self.news), Review.STATUS_REJECTED)
        self.assertEqual(status_of(self.activity), Review.STATUS_PENDING)
        self.assertIsNone(status_of(News.objects.create(title="bare", author=self.owner)))

    def test_comment_for_owner_and_moderator_only(self):
        self.assertEqual(comment_for(self.news, self.owner), "改标题")
        self.assertEqual(comment_for(self.news, self.mod), "改标题")
        self.assertEqual(comment_for(self.news, self.other), "")
        self.assertEqual(comment_for(self.news, None), "")

    def test_comment_for_activity_without_related_kwarg(self):
        self.assertEqual(comment_for(self.activity, self.owner), "活动评语")
        self.assertEqual(comment_for(self.activity, self.other), "")


class VisibleQuerysetTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="x")
        self.other = User.objects.create_user(username="other", password="x")
        self.mod = _grant_moderate(User.objects.create_user(username="mod", password="x"))
        self.pending = News.objects.create(title="pending", author=self.owner, is_published=True)
        Review.objects.create(target=target_of(self.pending), status=Review.STATUS_PENDING)
        self.approved = News.objects.create(title="approved", author=self.owner, is_published=True)
        Review.objects.create(target=target_of(self.approved), status=Review.STATUS_APPROVED)

    def _ids(self, qs):
        return set(qs.values_list("pk", flat=True))

    def test_list_is_public_only(self):
        qs = visible_queryset(News.objects.all(), self.owner, "news", action="list")
        self.assertEqual(self._ids(qs), {self.approved.pk})

    def test_retrieve_author_preview(self):
        qs = visible_queryset(News.objects.all(), self.owner, "news", action="retrieve")
        self.assertEqual(self._ids(qs), {self.pending.pk, self.approved.pk})

    def test_retrieve_other_sees_public_only(self):
        qs = visible_queryset(News.objects.all(), self.other, "news", action="retrieve")
        self.assertEqual(self._ids(qs), {self.approved.pk})

    def test_retrieve_moderator_sees_all(self):
        qs = visible_queryset(News.objects.all(), self.mod, "news", action="retrieve")
        self.assertEqual(self._ids(qs), {self.pending.pk, self.approved.pk})

    def test_activity_list_includes_isnull_fixture(self):
        orphan = Activity.objects.create(
            type="deliberation", status="open", title="fixture", creator=self.owner,
        )
        pending = Activity.objects.create(
            type="deliberation", status="open", title="pending", creator=self.owner,
        )
        Review.objects.create(target=target_of(pending), status=Review.STATUS_PENDING)
        qs = visible_queryset(Activity.objects.all(), self.other, "activity", action="list")
        self.assertIn(orphan.pk, self._ids(qs))
        self.assertNotIn(pending.pk, self._ids(qs))
