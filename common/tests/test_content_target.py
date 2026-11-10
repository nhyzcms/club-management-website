"""ContentTarget 锚点表的契约测试（B1）。

B1 只做「加表 + 双写」，不改读路径。所以这里验的不是「功能对不对」，而是
三条**结构契约**：

1. 注册表自洽（``KIND_CHOICES`` ↔ ``KIND_TO_MODEL`` 一一对应，模型都能解析）；
2. 双写兜底真的生效（任何写路径落库后 ``target`` 都不为空）；
3. 级联链完整（删宿主 → 删 target → 带走挂在它上面的一切）。

第 3 条是最容易做漏的地方：``News → CommentThread → Comment → ReportCase``
是三跳，中间任一环没接上，删新闻就会留下悬空的评论或举报案。
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from activities.models import Activity, Exhibit, Submission
from attachments.create import create_attachment
from attachments.models import Attachment
from common.models import ContentTarget, Tag  # noqa: F401  （Tag 用于确认 common 已加载）
from common.targets import (
    KIND_TO_MODEL,
    audit_registry,
    content_host,
    host_ref,
    kind_of,
    model_for,
    related_to,
    target_for,
    target_of,
)
from messaging.models import Comment, CommentThread
from messaging.services import thread_for
from news.models import News
from reviews.models import Feedback, ReportCase, Review
from tasks.models import Task
from tutorials.models import Tutorial


class RegistryTest(TestCase):
    def test_registry_is_consistent(self):
        self.assertEqual(audit_registry(), [])

    def test_every_kind_resolves_to_a_model(self):
        for kind in KIND_TO_MODEL:
            with self.subTest(kind=kind):
                model = model_for(kind)
                self.assertEqual(kind_of(model()), kind)

    def test_unknown_kind_raises(self):
        with self.assertRaises(LookupError):
            model_for("nope")

    def test_kind_of_unregistered_model_raises(self):
        with self.assertRaises(LookupError):
            kind_of(ContentTarget())


class TargetForTest(TestCase):
    def test_idempotent(self):
        a = target_for("news", 1)
        b = target_for("news", 1)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(ContentTarget.objects.count(), 1)

    def test_same_id_different_kind_are_distinct_rows(self):
        a = target_for("news", 7)
        b = target_for("comment", 7)
        self.assertNotEqual(a.pk, b.pk)
        self.assertEqual(ContentTarget.objects.count(), 2)

    def test_none_object_id_rejected(self):
        with self.assertRaises(ValueError):
            target_for("news", None)


class FixtureMixin:
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="x")

    def make_news(self, title="新闻"):
        return News.objects.create(title=title, author=self.user)


class TargetAnchorTest(FixtureMixin, TestCase):
    """内容行只通过 ``target`` 锚定宿主——B9 删掉旧列之后这是唯一表示。

    原 ``LegacyColumnsBackfillTest`` 测的是「走旧列创建时 save() 自动补 target」，
    那个 mixin 已随旧列一起删除，这里改为钉「创建路径确实写 target」。
    """

    def test_attachment_from_parent_gets_target(self):
        news = self.make_news()
        att = create_attachment(
            user=self.user, parent=news,
            file=SimpleUploadedFile("a.txt", b"hi", content_type="text/plain"),
        )
        self.assertIsNotNone(att.target_id)
        self.assertEqual((att.target.kind, att.target.object_id), ("news", news.pk))

    def test_comment_thread_from_news_gets_target(self):
        news = self.make_news()
        thread = CommentThread.objects.create(target=target_of(news))
        self.assertEqual((thread.target.kind, thread.target.object_id), ("news", news.pk))

    def test_review_from_news_gets_target(self):
        news = self.make_news()
        review = Review.objects.create(target=target_of(news))
        self.assertEqual((review.target.kind, review.target.object_id), ("news", news.pk))

    def test_report_case_from_comment_gets_target(self):
        news = self.make_news()
        thread = CommentThread.objects.create(target=target_of(news))
        comment = Comment.objects.create(thread=thread, author=self.user, content="x")
        case = ReportCase.objects.create(target=target_of(comment))
        self.assertEqual((case.target.kind, case.target.object_id), ("comment", comment.pk))

    def test_explicit_target_is_not_overwritten(self):
        news = self.make_news()
        target = target_for("news", news.pk)
        review = Review.objects.create(target=target_of(news))
        self.assertEqual(review.target_id, target.pk)

    def test_row_without_target_is_tolerated(self):
        """``target`` 为空的排在 DB 层是允许的。

        「必须有宿主」由创建路径（``create_attachment`` / ``open_review`` /
        ``thread_for``）保证，不靠数据库约束——删列后没有合理默认值可以填进
        非空约束。读取路径遇到这种行要安静返回 None，而不是炸。
        """
        review = Review.objects.create()
        fresh = Review.objects.get(pk=review.pk)
        self.assertIsNone(host_ref(fresh))
        self.assertIsNone(content_host(fresh))


class CascadeChainTest(FixtureMixin, TestCase):
    """删宿主 → 删 target → 带走挂在它上面的一切。"""

    def test_deleting_news_removes_every_attached_thing(self):
        news = self.make_news()
        thread = CommentThread.objects.create(target=target_of(news))
        comment = Comment.objects.create(thread=thread, author=self.user, content="评")
        review = Review.objects.create(target=target_of(news))
        comment_case = ReportCase.objects.create(target=target_of(comment))
        news_case = ReportCase.objects.create(target=target_of(news))
        att = create_attachment(
            user=self.user, parent=news,
            file=SimpleUploadedFile("a.txt", b"hi", content_type="text/plain"),
        )
        target_id = target_of(news).pk

        news.delete()

        self.assertFalse(ContentTarget.objects.filter(pk=target_id).exists())
        self.assertFalse(CommentThread.objects.filter(pk=thread.pk).exists())
        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())
        self.assertFalse(Attachment.objects.filter(pk=att.pk).exists())
        self.assertFalse(ReportCase.objects.filter(pk__in=[comment_case.pk, news_case.pk]).exists())

    def test_deleting_comment_removes_its_report_case_but_keeps_thread(self):
        """评论的 target 独立于宿主的 target——删评论不该动评论区。"""
        news = self.make_news()
        thread = CommentThread.objects.create(target=target_of(news))
        comment = Comment.objects.create(thread=thread, author=self.user, content="评")
        case = ReportCase.objects.create(target=target_of(comment))
        comment_target = target_of(comment).pk

        comment.delete()

        self.assertFalse(ContentTarget.objects.filter(pk=comment_target).exists())
        self.assertFalse(ReportCase.objects.filter(pk=case.pk).exists())
        self.assertTrue(CommentThread.objects.filter(pk=thread.pk).exists())

    def test_deleting_activity_cascades_through_submission(self):
        """两跳：活动 → 作品 → 作品上的附件。"""
        activity = Activity.objects.create(type="collection", status="collecting", title="征集")
        submission = Submission.objects.create(activity=activity, submitter=self.user)
        att = create_attachment(
            user=self.user, parent=submission,
            file=SimpleUploadedFile("b.txt", b"yo", content_type="text/plain"),
        )
        self.assertEqual(att.target.kind, "submission")

        activity.delete()

        self.assertFalse(Submission.objects.filter(pk=submission.pk).exists())
        self.assertFalse(Attachment.objects.filter(pk=att.pk).exists())
        self.assertFalse(
            ContentTarget.objects.filter(kind="submission", object_id=submission.pk).exists()
        )

    def test_orphan_target_alone_does_not_delete_host(self):
        """反向不成立：手动删 target 只带走内容，不该动宿主。"""
        news = self.make_news()
        target = target_of(news)
        target.delete()
        self.assertTrue(News.objects.filter(pk=news.pk).exists())


class RelatedToTest(FixtureMixin, TestCase):
    """``related_to`` 按 ``(kind, object_id)`` 定位宿主。

    原实现有一个 ``Q(**{kind: host})`` 的旧列分支，B9 删列后去掉了——所以这里
    不再测「target 为空时靠旧列匹配」。
    """

    def test_matches_by_target(self):
        news = self.make_news()
        thread = CommentThread.objects.create(target=target_of(news))
        self.assertEqual(list(related_to(CommentThread, news)), [thread])

    def test_does_not_match_other_hosts(self):
        news = self.make_news()
        other = self.make_news("别的")
        CommentThread.objects.create(target=target_of(news))
        self.assertEqual(list(related_to(CommentThread, other)), [])

    def test_row_without_target_is_not_matched(self):
        """没有 target 的行不属于任何宿主——不是「匹配所有人」。"""
        news = self.make_news()
        CommentThread.objects.create()
        self.assertEqual(list(related_to(CommentThread, news)), [])

    def test_review_lookup_by_host(self):
        news = self.make_news()
        review = Review.objects.create(target=target_of(news))
        self.assertEqual(list(related_to(Review, news)), [review])

    def test_host_ref_reads_target(self):
        news = self.make_news()
        review = Review.objects.create(target=target_of(news))
        self.assertEqual(host_ref(review), ("news", news.pk))

    def test_content_host_returns_instance(self):
        news = self.make_news()
        review = Review.objects.create(target=target_of(news))
        self.assertEqual(content_host(review).pk, news.pk)

    def test_content_host_is_none_without_target(self):
        review = Review.objects.create()
        self.assertIsNone(content_host(review))


class ThreadForTest(FixtureMixin, TestCase):
    """``thread_for`` 仍然是「每个宿主恰好一条」评论区。"""

    def test_returns_same_thread_on_repeat_calls(self):
        news = self.make_news()
        a = thread_for(news)
        b = thread_for(news)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(CommentThread.objects.count(), 1)

    def test_task_host_still_works(self):
        task = Task.objects.create(title="任务", creator=self.user)
        thread = thread_for(task)
        self.assertEqual(thread.target.kind, "task")

    def test_unsupported_host_rejected(self):
        with self.assertRaises(Exception):
            thread_for(self.user)


class ContentHostTest(FixtureMixin, TestCase):
    def test_attachment_parent_resolution(self):
        from attachments.create import parent_of

        news = self.make_news()
        att = create_attachment(
            user=self.user, parent=news,
            file=SimpleUploadedFile("a.txt", b"hi", content_type="text/plain"),
        )
        self.assertEqual(parent_of(att).pk, news.pk)

    def test_attachment_without_target_has_no_parent(self):
        """没有 target 的附件解析不出父级——返回 None，不炸。"""
        from attachments.create import parent_of

        att = Attachment.objects.create(
            uploaded_by=self.user,
            file=SimpleUploadedFile("b.txt", b"hi", content_type="text/plain"),
            file_type="document", file_name="b.txt", file_size=2,
        )
        self.assertIsNone(parent_of(att))


class AllKindsSmokeTest(FixtureMixin, TestCase):
    """8 种 kind 各建一条 target，确认都能落库（防止 registry 里写错模型名）。"""

    def test_every_kind_can_be_registered(self):
        for kind in KIND_TO_MODEL:
            with self.subTest(kind=kind):
                target = target_for(kind, 99999)
                self.assertEqual(target.kind, kind)
                self.assertEqual(target.object_id, 99999)

    def test_kind_display_is_chinese(self):
        """后台展示要可读——get_kind_display 不能回落成英文 key。"""
        target = target_for("news", 1)
        self.assertEqual(str(target), "新闻#1")


class HostModelsStillUsableTest(FixtureMixin, TestCase):
    """顺手钉住四个宿主模型都还在 registry 里（新增宿主时别忘了这里）。"""

    def test_all_hosts_are_registered(self):
        self.assertEqual(
            set(KIND_TO_MODEL),
            {"news", "activity", "tutorial", "task", "comment", "submission", "exhibit", "feedback"},
        )

    def test_model_types(self):
        self.assertIs(model_for("news"), News)
        self.assertIs(model_for("activity"), Activity)
        self.assertIs(model_for("tutorial"), Tutorial)
        self.assertIs(model_for("task"), Task)
        self.assertIs(model_for("comment"), Comment)
        self.assertIs(model_for("submission"), Submission)
        self.assertIs(model_for("exhibit"), Exhibit)
        self.assertIs(model_for("feedback"), Feedback)
