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


class LegacyColumnsBackfillTest(FixtureMixin, TestCase):
    """双写兜底：走旧列创建的行，``target`` 必须自动补上。

    这四张表的写路径散落在视图、序列化器、管理命令与测试夹具里；只要有一个
    入口没写 target，PR 2 切读之后那些行就查不到了。
    """

    def test_attachment_from_news_gets_target(self):
        news = self.make_news()
        att = create_attachment(
            user=self.user, parent=news,
            file=SimpleUploadedFile("a.txt", b"hi", content_type="text/plain"),
        )
        self.assertIsNotNone(att.target_id)
        self.assertEqual((att.target.kind, att.target.object_id), ("news", news.pk))

    def test_comment_thread_from_news_gets_target(self):
        news = self.make_news()
        thread = CommentThread.objects.create(news=news)
        self.assertEqual((thread.target.kind, thread.target.object_id), ("news", news.pk))

    def test_review_from_news_gets_target(self):
        news = self.make_news()
        review = Review.objects.create(news=news)
        self.assertEqual((review.target.kind, review.target.object_id), ("news", news.pk))

    def test_report_case_from_comment_gets_target(self):
        news = self.make_news()
        thread = CommentThread.objects.create(news=news)
        comment = Comment.objects.create(thread=thread, author=self.user, content="x")
        case = ReportCase.objects.create(comment=comment)
        self.assertEqual((case.target.kind, case.target.object_id), ("comment", comment.pk))

    def test_explicit_target_is_not_overwritten(self):
        news = self.make_news()
        target = target_for("news", news.pk)
        review = Review.objects.create(news=news, target=target)
        self.assertEqual(review.target_id, target.pk)

    def test_saving_without_parent_does_not_crash(self):
        """既没有 target 也没有旧列时不该炸——让 DB 约束去报错。"""
        review = Review()
        with self.assertRaises(Exception):
            review.save()


class CascadeChainTest(FixtureMixin, TestCase):
    """删宿主 → 删 target → 带走挂在它上面的一切。"""

    def test_deleting_news_removes_every_attached_thing(self):
        news = self.make_news()
        thread = CommentThread.objects.create(news=news)
        comment = Comment.objects.create(thread=thread, author=self.user, content="评")
        review = Review.objects.create(news=news)
        comment_case = ReportCase.objects.create(comment=comment)
        news_case = ReportCase.objects.create(news=news)
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
        thread = CommentThread.objects.create(news=news)
        comment = Comment.objects.create(thread=thread, author=self.user, content="评")
        case = ReportCase.objects.create(comment=comment)
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
    """``related_to`` 的两个分支都要真的工作。

    切读期的核心风险：如果只按 ``target`` 查，任何 target 为空的存量行都会
    「凭空消失」（评论没了、审核队列少了条目）。所以必须两条路都走，且两条路
    各自单独可用。
    """

    def test_matches_by_legacy_column_when_target_is_null(self):
        news = self.make_news()
        thread = CommentThread.objects.create(news=news)
        # 绕过 save() 清掉 target，模拟「回填漏掉的存量行」
        CommentThread.objects.filter(pk=thread.pk).update(target=None)
        found = related_to(CommentThread, news)
        self.assertEqual(list(found), [CommentThread.objects.get(pk=thread.pk)])

    def test_matches_by_target_when_legacy_column_points_elsewhere(self):
        news_a = self.make_news("A")
        news_b = self.make_news("B")
        thread = CommentThread.objects.create(news=news_a)
        # 绕过 save() 把 target 指向 B：旧列仍指向 A，target 指向 B
        CommentThread.objects.filter(pk=thread.pk).update(target=target_for("news", news_b.pk))
        self.assertEqual(list(related_to(CommentThread, news_a)), [thread])
        self.assertEqual(list(related_to(CommentThread, news_b)), [thread])

    def test_does_not_match_other_hosts(self):
        news = self.make_news()
        other = self.make_news("别的")
        CommentThread.objects.create(news=news)
        self.assertEqual(list(related_to(CommentThread, other)), [])

    def test_works_for_tables_without_that_column(self):
        """``CommentThread`` 没有 ``comment`` 列——确认不会拼出非法字段名。"""
        thread = CommentThread.objects.create(news=self.make_news())
        comment = Comment.objects.create(thread=thread, author=self.user, content="x")
        self.assertEqual(list(related_to(CommentThread, comment)), [])

    def test_review_lookup_by_host(self):
        news = self.make_news()
        review = Review.objects.create(news=news)
        self.assertEqual(list(related_to(Review, news)), [review])

    def test_host_ref_prefers_target_then_legacy(self):
        news = self.make_news()
        review = Review.objects.create(news=news)
        self.assertEqual(host_ref(review), ("news", news.pk))
        Review.objects.filter(pk=review.pk).update(target=None)
        self.assertEqual(host_ref(Review.objects.get(pk=review.pk)), ("news", news.pk))

    def test_content_host_returns_instance(self):
        news = self.make_news()
        review = Review.objects.create(news=news)
        self.assertEqual(content_host(review).pk, news.pk)
        Review.objects.filter(pk=review.pk).update(target=None)
        self.assertEqual(content_host(Review.objects.get(pk=review.pk)).pk, news.pk)


class ThreadForTest(FixtureMixin, TestCase):
    """``thread_for`` 切读后仍然是「恰好一条」，且不会因 target 为空而重复建。"""

    def test_returns_same_thread_on_repeat_calls(self):
        news = self.make_news()
        a = thread_for(news)
        b = thread_for(news)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(CommentThread.objects.count(), 1)

    def test_reuses_legacy_row_and_backfills_target(self):
        news = self.make_news()
        legacy = CommentThread.objects.create(news=news)
        CommentThread.objects.filter(pk=legacy.pk).update(target=None)

        thread = thread_for(news)

        self.assertEqual(thread.pk, legacy.pk)
        self.assertIsNotNone(thread.target_id, "命中存量行后应把 target 补上")
        self.assertEqual(CommentThread.objects.count(), 1, "不该重复创建")

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
        Attachment.objects.filter(pk=att.pk).update(target=None)
        self.assertEqual(parent_of(Attachment.objects.get(pk=att.pk)).pk, news.pk)


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
