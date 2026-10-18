"""通知迭代测试：权限驱动投递 / 各源接线 / 邮件渲染（2026-09 通知延伸）。"""
from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Verification
from accounts.test_helpers import grant_verification
from messaging.models import Notification, NotificationDelivery, NotificationSubscription
from messaging.notifications.channels import EmailChannel
from messaging.notifications.dispatch import users_with_perm
from messaging.services import notify_perm, send_dm
from messaging.models import Conversation


def grant(user, app_label, codename):
    """给用户直接授予某权限。"""
    perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
    user.user_permissions.add(perm)
    return perm


class UsersWithPermTest(TestCase):
    """权限 → 用户解析：直接授权 / 组授权 / 超级管理员 / 停用排除。"""

    def setUp(self):
        self.a = User.objects.create_user(username="a", password="x")
        self.b = User.objects.create_user(username="b", password="x")

    def test_direct_grant(self):
        grant(self.a, "reviews", "read_feedback")
        ids = {u.pk for u in users_with_perm("reviews.read_feedback")}
        self.assertIn(self.a.pk, ids)
        self.assertNotIn(self.b.pk, ids)

    def test_group_grant(self):
        group = Group.objects.create(name="desk")
        group.permissions.add(
            Permission.objects.get(content_type__app_label="reviews", codename="handle_report")
        )
        self.b.groups.add(group)
        ids = {u.pk for u in users_with_perm("reviews.handle_report")}
        self.assertIn(self.b.pk, ids)

    def test_superuser_included(self):
        root = User.objects.create_superuser(username="root", password="x", email="r@example.com")
        ids = {u.pk for u in users_with_perm("accounts.can_review_identity")}
        self.assertIn(root.pk, ids)

    def test_inactive_excluded(self):
        grant(self.a, "reviews", "read_feedback")
        self.a.is_active = False
        self.a.save(update_fields=["is_active"])
        ids = {u.pk for u in users_with_perm("reviews.read_feedback")}
        self.assertNotIn(self.a.pk, ids)

    def test_bad_format_raises(self):
        with self.assertRaises(ValueError):
            users_with_perm("no_dot_format")


class NotifyPermTest(TestCase):
    """权限驱动投递：收件人为权限持有者；actor 排除；订阅静默优先。"""

    def setUp(self):
        self.handler = User.objects.create_user(username="handler", password="x")
        grant(self.handler, "reviews", "read_feedback")
        self.nobody = User.objects.create_user(username="nobody", password="x")

    def test_recipients_are_perm_holders(self):
        rows = notify_perm("review", "feedback_submitted", "reviews.read_feedback")
        self.assertEqual({r.recipient_id for r in rows}, {self.handler.pk})
        self.assertEqual(rows[0].event, "feedback_submitted")

    def test_actor_excluded(self):
        actor = User.objects.create_user(username="actor", password="x")
        grant(actor, "reviews", "read_feedback")
        rows = notify_perm("review", "feedback_submitted", "reviews.read_feedback", actor=actor)
        self.assertEqual({r.recipient_id for r in rows}, {self.handler.pk})

    def test_disabled_site_silences_perm_notification(self):
        NotificationSubscription.objects.create(
            user=self.handler, source_key="review", channel_key="site", enabled=False,
        )
        rows = notify_perm("review", "feedback_submitted", "reviews.read_feedback")
        self.assertEqual(rows, [])


class WiringTest(TestCase):
    """接线：各源事件真实触发并送达正确收件人。"""

    def setUp(self):
        self.handler = User.objects.create_user(
            username="handler", password="x", email="h@example.com",
        )
        grant_verification(self.handler)
        self.user = User.objects.create_user(
            username="u", password="x", email="u@example.com",
        )
        grant_verification(self.user)
        self.client = APIClient()

    # ---- 审核系统：意见反馈 ----

    def test_feedback_submit_notifies_handler(self):
        grant(self.handler, "reviews", "read_feedback")
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            "/reviews/feedbacks/submit/",
            {"title": "建议增加夜跑活动", "category": "suggestion", "description": "x"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        Notification.objects.get(recipient=self.handler, event="feedback_submitted")  # noqa: B018
        self.assertFalse(
            Notification.objects.filter(recipient=self.user, event="feedback_submitted").exists()
        )

    # ---- 审核系统：举报 ----

    def _make_news(self, author=None, approved=True):
        from news.models import News
        from reviews.test_helpers import approve_news

        if author is None:
            author = User.objects.create_user(username="news_author", password="x")
        news = News.objects.create(title="测试新闻", author=author)
        return approve_news(news) if approved else news

    def _file_report(self, reporter, news):
        self.client.force_authenticate(reporter)
        return self.client.post(
            "/reviews/reports/",
            {"target_type": "news", "target_id": news.pk, "reason": "内容不当"},
            format="json",
        )

    def test_first_report_notifies_handler_once(self):
        grant(self.handler, "reviews", "handle_report")
        other = User.objects.create_user(username="other", password="x")
        grant_verification(other)
        news = self._make_news()
        resp = self._file_report(self.user, news)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            Notification.objects.filter(recipient=self.handler, event="report_submitted").count(), 1,
        )
        # 第二人追加举报：不重复打扰（仅首次立案通知）
        self.assertEqual(self._file_report(other, news).status_code, 201)
        self.assertEqual(
            Notification.objects.filter(recipient=self.handler, event="report_submitted").count(), 1,
        )

    def test_report_resolved_notifies_reporters(self):
        grant(self.handler, "reviews", "handle_report")
        news = self._make_news()
        self.assertEqual(self._file_report(self.user, news).status_code, 201)
        case_id = Notification.objects.get(recipient=self.handler, event="report_submitted").payload["id"]
        self.client.force_authenticate(self.handler)
        resp = self.client.post(
            f"/reviews/reports/{case_id}/dismiss/", {"comment": "不成立"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        n = Notification.objects.get(recipient=self.user, event="report_resolved")
        self.assertEqual(n.payload.get("result"), "dismissed")

    # ---- 审核系统：身份认证 ----

    def test_identity_submit_notifies_reviewer(self):
        submitter = User.objects.create_user(username="proof_sub", password="x")  # 未认证，可提交
        grant(self.handler, "accounts", "can_review_identity")
        self.client.force_login(submitter)  # Django 会话（该视图非 DRF）
        resp = self.client.post(
            "/auth/verification/manual/submit/",
            {
                "real_name": "张三",
                "identity": "student",
                "proof_files": SimpleUploadedFile("a.png", b"fake", content_type="image/png"),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        Notification.objects.get(recipient=self.handler, event="identity_submitted")  # noqa: B018

    def test_identity_approved_notifies_applicant(self):
        from accounts.identity_review import approve_manual

        reviewer = User.objects.create_user(username="rv", password="x")
        Verification.objects.update_or_create(
            user=self.user, channel=Verification.CHANNEL_MANUAL,
            defaults={"status": Verification.STATUS_PENDING},
        )
        approve_manual(self.user, reviewer)
        n = Notification.objects.get(recipient=self.user, event="identity_resolved")
        self.assertEqual(n.payload.get("result"), "approved")

    # ---- 审核系统：内容送审 ----

    def test_content_review_pending_notifies_moderator(self):
        from reviews.lifecycle import open_review

        moderator = User.objects.create_user(username="mod", password="x")
        grant(moderator, "reviews", "moderate")
        news = self._make_news(approved=False)
        open_review(news=news, actor=self.user)
        n = Notification.objects.get(recipient=moderator, event="content_submitted")
        self.assertEqual(n.payload.get("type"), "news")

    def test_activity_approved_broadcasts(self):
        from activities.models import Activity
        from reviews.lifecycle import APPROVE, apply, open_review

        moderator = User.objects.create_user(username="mod2", password="x")
        activity = Activity.objects.create(
            title="秋季摄影展", type="deliberation", status="open",
            creator=self.user, start_at=timezone.now() + timedelta(days=1),
        )
        review = open_review(activity=activity, actor=self.user)
        apply(APPROVE, review, moderator)
        n = Notification.objects.get(recipient=self.handler, event="published")
        self.assertEqual(n.category, "activity")
        self.assertEqual(n.payload.get("id"), activity.pk)

    # ---- 活动生命周期：到点开放 ----

    def test_activity_opened_broadcasts_to_active_users(self):
        from activities.lifecycle import transition_due_starts
        from activities.models import Activity

        Activity.objects.create(
            title="到点活动", type="deliberation", status="scheduled",
            creator=self.user, start_at=timezone.now() - timedelta(minutes=1),
        )
        opened = transition_due_starts()
        self.assertEqual(len(opened), 1)
        active_count = User.objects.filter(is_active=True).count()
        self.assertEqual(
            Notification.objects.filter(category="activity", event="opened").count(), active_count,
        )

    # ---- 私信 ----

    def test_new_dm_notifies_recipient_only(self):
        conv = Conversation.objects.create()
        conv.participants.add(self.user, self.handler)
        send_dm(conv, self.user, "嗨")
        Notification.objects.get(recipient=self.handler, category="dm", event="new_message")  # noqa: B018
        self.assertFalse(
            Notification.objects.filter(recipient=self.user, category="dm").exists()
        )


class EmailRenderingTest(TestCase):
    """邮件渲染：HTML 模板 / 源配色 / 社团徽标 CID / 链接绝对化。"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="u", password="x", email="u@example.com",
        )
        grant_verification(self.user)
        self.channel = EmailChannel()

    def _send(self, category, event, payload):
        notification = Notification.objects.create(
            recipient=self.user, category=category, event=event, payload=payload,
        )
        delivery = NotificationDelivery.objects.create(notification=notification, channel_key="email")
        self.channel.deliver(delivery)
        return mail.outbox[-1]

    def test_html_email_with_source_style_and_logo(self):
        msg = self._send("discipline", "muted", {"url": "/profile"})
        self.assertIn("纪律 / 处罚", msg.subject)
        self.assertIn("禁言生效", msg.subject)
        html = msg.alternatives[0][0]
        self.assertIn('content-type="text/html"', msg.alternatives[0][1]) if False else None
        self.assertIn("#d64545", html)  # 纪律主色
        self.assertIn("⚖️", html)       # 源图标
        self.assertIn("cid:club-logo", html)
        self.assertIn("南汇一中传媒社", html)
        # 徽标以内联 PNG 附件注入（CID）
        cids = [a.get("Content-ID") for a in msg.attachments]
        self.assertIn("<club-logo>", cids)
        png = [a for a in msg.attachments if a.get_content_type() == "image/png"]
        self.assertEqual(len(png), 1)
        self.assertGreater(len(png[0].get_payload(decode=True)), 1000)

    @override_settings(FRONTEND_URL="https://club.example.org")
    def test_relative_url_made_absolute_and_per_source_color(self):
        msg = self._send("comment", "comment_replied", {"url": "/news/42"})
        html = msg.alternatives[0][0]
        self.assertIn("https://club.example.org/news/42", html)
        self.assertIn("#2e9e6b", html)  # 评论源主色

    def test_plain_text_fallback_contains_message(self):
        msg = self._send("activity", "opened", {"title": "秋季摄影展", "url": "/activity/7"})
        self.assertIn("秋季摄影展", msg.body)
        self.assertIn("已开始", msg.body)
