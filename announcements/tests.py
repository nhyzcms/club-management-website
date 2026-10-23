"""全站弹窗公告（ADR-0042）：受众口径 / 弹窗可见性 / 发布副作用 / 已读台账 / 鉴权端点。

覆盖点：
- 受众 SQL 与 ``is_verified`` / ``admin_identity_valid`` 同口径（含「过期通道不算已认证」）；
- 弹窗列表：只给「在线 + 在受众内 + 未读」的公告，已读后不再出现，跨用户互不影响；
- 发布：站内通知落库 + 可选邮件（只发已认证邮箱）+ 幂等；
- 端点：匿名只看全站受众，详情 / 原件对受众外一律 404；
- 后台：没有 ``announcements.manage_announcements`` 进不去，有权限保存「已发布」即推送。
"""
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Verification
from accounts.test_helpers import grant_verification
from messaging.models import Notification, NotificationDelivery

from .models import Announcement, AnnouncementRead
from .services import (
    audience_matches,
    active_for,
    can_see,
    publish,
    recipient_queryset,
    stats,
)


def _announcement(**kwargs) -> Announcement:
    defaults = {
        "title": "测试公告",
        "summary": "正文",
        "audience": Announcement.AUDIENCE_REGISTERED,
    }
    defaults.update(kwargs)
    return Announcement.objects.create(**defaults)


class AudienceTest(TestCase):
    """受众解析：SQL 与 Python 判定必须一致。"""

    def setUp(self):
        self.plain = User.objects.create_user("plain", password="p")
        self.verified = grant_verification(User.objects.create_user("verified", password="p"))
        self.expired = grant_verification(User.objects.create_user("expired", password="p"))
        Verification.objects.filter(user=self.expired).update(
            expires_at=timezone.now() - timedelta(days=1),
        )
        # is_staff=True 会经 post_save 信号自动补「后台委任」通道（accounts.models.sync_appointment_channel）
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.boss = User.objects.create_user("boss", password="p", is_staff=True, is_superuser=True)

    def test_registered_audience_matches_every_active_account(self):
        self.assertEqual(
            recipient_queryset(Announcement.AUDIENCE_REGISTERED).count(), 5,
        )

    def test_verified_audience_skips_expired_channel(self):
        ids = set(
            recipient_queryset(Announcement.AUDIENCE_VERIFIED).values_list("pk", flat=True)
        )
        self.assertIn(self.verified.pk, ids)
        self.assertIn(self.staff.pk, ids)  # 委任通道未过期 → 已认证
        self.assertNotIn(self.expired.pk, ids)  # 过期通道不再算已认证
        self.assertNotIn(self.plain.pk, ids)

    def test_admin_audience_requires_valid_appointment(self):
        ids = set(
            recipient_queryset(Announcement.AUDIENCE_ADMIN).values_list("pk", flat=True)
        )
        self.assertIn(self.staff.pk, ids)
        self.assertIn(self.boss.pk, ids)
        self.assertNotIn(self.verified.pk, ids)

    def test_python_audience_matches_sql(self):
        for audience in (
            Announcement.AUDIENCE_ALL,
            Announcement.AUDIENCE_REGISTERED,
            Announcement.AUDIENCE_VERIFIED,
            Announcement.AUDIENCE_ADMIN,
        ):
            sql_ids = set(recipient_queryset(audience).values_list("pk", flat=True))
            for user in (self.plain, self.verified, self.expired, self.staff, self.boss):
                self.assertEqual(
                    audience_matches(user, audience),
                    user.pk in sql_ids,
                    f"受众 {audience} 在 {user.username} 上口径不一致",
                )

    def test_anonymous_only_matches_all_audience(self):
        self.assertTrue(audience_matches(None, Announcement.AUDIENCE_ALL))
        for audience in (
            Announcement.AUDIENCE_REGISTERED,
            Announcement.AUDIENCE_VERIFIED,
            Announcement.AUDIENCE_ADMIN,
        ):
            self.assertFalse(audience_matches(None, audience))


class ActiveForTest(TestCase):
    def setUp(self):
        self.alice = grant_verification(User.objects.create_user("alice", password="p"))
        self.bob = grant_verification(User.objects.create_user("bob", password="p"))

    def test_only_live_published_and_unread(self):
        live = _announcement(title="在线")
        publish(live)
        _announcement(title="草稿")  # 未发布
        expired = _announcement(title="过期")
        publish(expired)
        Announcement.objects.filter(pk=expired.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        expired.refresh_from_db()

        self.assertEqual([row.title for row in active_for(self.alice)], ["在线"])
        self.assertTrue(can_see(self.alice, live))
        self.assertFalse(can_see(self.alice, expired))

        AnnouncementRead.objects.create(announcement=live, user=self.alice)
        self.assertEqual(active_for(self.alice), [])
        self.assertEqual(len(active_for(self.bob)), 1)  # 别人的已读不影响我

    def test_audience_filter_applies_to_popup(self):
        admin = User.objects.create_user("admin", password="p", is_staff=True)
        row = _announcement(
            title="只有管理员", audience=Announcement.AUDIENCE_ADMIN,
        )
        publish(row)
        self.assertEqual(active_for(self.alice), [])
        self.assertEqual(active_for(admin), [row])

    def test_anonymous_sees_all_audience_only(self):
        class Anon:
            is_authenticated = False

        row = _announcement(title="全站", audience=Announcement.AUDIENCE_ALL)
        publish(row)
        self.assertEqual(active_for(Anon()), [row])


class PublishTest(TestCase):
    def setUp(self):
        self.alice = grant_verification(User.objects.create_user("alice", email="a@163.com", password="p"))
        self.unverified = User.objects.create_user("unverified", email="u@163.com", password="p")

    def test_publish_creates_site_notifications_with_announcement_link(self):
        row = _announcement(audience=Announcement.AUDIENCE_REGISTERED)
        result = publish(row, actor=self.alice)

        self.assertEqual(result["recipients"], 2)
        self.assertEqual(result["notified"], 2)
        row.refresh_from_db()
        self.assertEqual(row.status, Announcement.STATUS_PUBLISHED)
        self.assertIsNotNone(row.published_at)

        note = Notification.objects.get(recipient=self.alice, category="announcement")
        self.assertEqual(note.payload["announcement_id"], row.pk)
        self.assertEqual(note.payload["url"], f"/announcements/{row.pk}")
        self.assertEqual(note.payload["title"], row.title)

    def test_publish_is_idempotent(self):
        row = _announcement(audience=Announcement.AUDIENCE_REGISTERED)
        publish(row)
        again = publish(row)
        self.assertTrue(again["already_published"])
        self.assertEqual(Notification.objects.filter(category="announcement").count(), 2)

    def test_email_only_goes_to_verified_mailboxes(self):
        row = _announcement(
            audience=Announcement.AUDIENCE_REGISTERED, send_email=True,
        )
        with self.captureOnCommitCallbacks(execute=True):
            publish(row)

        deliveries = NotificationDelivery.objects.filter(channel_key="email")
        self.assertEqual(deliveries.count(), 1)  # 只有 alice（邮箱已认证）
        self.assertEqual(deliveries.first().notification.recipient, self.alice)
        self.assertEqual(deliveries.first().status, NotificationDelivery.STATUS_SENT)

    def test_no_email_delivery_when_option_off(self):
        row = _announcement(audience=Announcement.AUDIENCE_REGISTERED)
        with self.captureOnCommitCallbacks(execute=True):
            publish(row)
        self.assertFalse(NotificationDelivery.objects.filter(channel_key="email").exists())


class ApiTest(TestCase):
    def setUp(self):
        self.alice = grant_verification(User.objects.create_user("alice", password="p"))
        self.plain = User.objects.create_user("plain", password="p")

    def _published(self, **kwargs):
        row = _announcement(**kwargs)
        publish(row)
        return row

    def test_active_requires_login_for_registered_audience(self):
        self._published(audience=Announcement.AUDIENCE_REGISTERED)
        anon = Client().get("/announcements/active/")
        self.assertEqual(anon.status_code, 200)
        self.assertEqual(anon.json()["count"], 0)

        client = Client()
        client.force_login(self.alice)
        self.assertEqual(client.get("/announcements/active/").json()["count"], 1)

    def test_read_marks_disappear_and_is_idempotent(self):
        row = self._published(audience=Announcement.AUDIENCE_REGISTERED)
        client = Client()
        client.force_login(self.alice)

        first = client.post(f"/announcements/{row.pk}/read/")
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["already_read"])

        second = client.post(f"/announcements/{row.pk}/read/")
        self.assertTrue(second.json()["already_read"])
        self.assertEqual(AnnouncementRead.objects.filter(announcement=row).count(), 1)
        self.assertEqual(client.get("/announcements/active/").json()["count"], 0)

    def test_read_requires_login(self):
        row = self._published(audience=Announcement.AUDIENCE_ALL)
        self.assertEqual(Client().post(f"/announcements/{row.pk}/read/").status_code, 403)

    def test_detail_and_file_respect_audience(self):
        pdf = SimpleUploadedFile("通知.pdf", b"%PDF-1.4 hello", content_type="application/pdf")
        row = _announcement(
            audience=Announcement.AUDIENCE_VERIFIED, summary="", document=pdf,
        )
        Announcement.objects.filter(pk=row.pk).update(
            document_name="通知.pdf", document_kind="pdf", document_size=len(b"%PDF-1.4 hello"),
        )
        publish(row)

        client = Client()
        client.force_login(self.plain)  # 未认证：不在受众内
        self.assertEqual(client.get(f"/announcements/{row.pk}/").status_code, 404)
        self.assertEqual(client.get(f"/announcements/{row.pk}/file/").status_code, 404)

        client.force_login(self.alice)
        detail = client.get(f"/announcements/{row.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["file_url"], f"/announcements/{row.pk}/file/")
        blob = client.get(f"/announcements/{row.pk}/file/")
        self.assertEqual(blob.status_code, 200)
        self.assertEqual(blob["Content-Type"], "application/pdf")
        self.assertIn("inline", blob["Content-Disposition"])

    def test_archived_announcement_is_hidden(self):
        row = self._published(audience=Announcement.AUDIENCE_ALL)
        client = Client()
        client.force_login(self.alice)
        self.assertEqual(client.get(f"/announcements/{row.pk}/").status_code, 200)
        Announcement.objects.filter(pk=row.pk).update(status=Announcement.STATUS_ARCHIVED)
        self.assertEqual(client.get(f"/announcements/{row.pk}/").status_code, 404)
        self.assertEqual(client.get("/announcements/active/").json()["count"], 0)


class StatsTest(TestCase):
    def test_stats_counts_readers_against_audience(self):
        alice = User.objects.create_user("alice", password="p")
        User.objects.create_user("bob", password="p")
        row = _announcement(audience=Announcement.AUDIENCE_REGISTERED)
        publish(row)
        AnnouncementRead.objects.create(announcement=row, user=alice)

        data = stats(row)
        self.assertEqual(data["recipients"], 2)
        self.assertEqual(data["read_count"], 1)
        self.assertEqual(data["unread_count"], 1)
        self.assertEqual(data["read_rate"], 50.0)


class AdminPermissionTest(TestCase):
    def setUp(self):
        self.row = _announcement(audience=Announcement.AUDIENCE_REGISTERED)

    def test_staff_without_permission_cannot_open_module(self):
        staff = User.objects.create_user("staff", password="p", is_staff=True)
        client = Client()
        client.force_login(staff)
        self.assertEqual(client.get("/admin/announcements/announcement/").status_code, 403)

    def test_group_permission_opens_module_and_grants_read_details(self):
        user = User.objects.create_user("president", password="p", is_staff=True)
        user.groups.add(Group.objects.get_or_create(name="社长")[0])
        client = Client()
        client.force_login(user)

        self.assertEqual(client.get("/admin/announcements/announcement/").status_code, 200)
        reads = client.get(f"/admin/announcements/announcement/{self.row.pk}/reads/")
        self.assertEqual(reads.status_code, 200)
        self.assertContains(reads, "已读明细")

    def test_change_page_renders_stats_panel(self):
        """统计栏必须能渲染（format_html 的比率格式化曾在这里炸过）。"""
        user = User.objects.create_user("boss2", password="p", is_staff=True, is_superuser=True)
        publish(self.row)
        AnnouncementRead.objects.create(announcement=self.row, user=user)
        client = Client()
        client.force_login(user)
        resp = client.get(f"/admin/announcements/announcement/{self.row.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "查看已读明细")
        self.assertContains(resp, "受众")

    def test_saving_as_published_pushes_once(self):
        user = User.objects.create_user("boss", password="p", is_staff=True, is_superuser=True)
        client = Client()
        client.force_login(user)
        payload = {
            "title": "后台发布",
            "summary": "正文",
            "audience": Announcement.AUDIENCE_REGISTERED,
            "status": Announcement.STATUS_PUBLISHED,
            "expires_at_0": "",
            "expires_at_1": "",
        }
        resp = client.post("/admin/announcements/announcement/add/", payload)
        self.assertEqual(resp.status_code, 302)
        row = Announcement.objects.get(title="后台发布")
        self.assertIsNotNone(row.published_at)
        self.assertEqual(
            Notification.objects.filter(
                category="announcement", payload__announcement_id=row.pk,
            ).count(),
            User.objects.filter(is_active=True).count(),
        )

        # 再保存一次（仍然是已发布）不应重复推送
        payload["summary"] = "改个错别字"
        client.post(f"/admin/announcements/announcement/{row.pk}/change/", payload)
        self.assertEqual(
            Notification.objects.filter(
                category="announcement", payload__announcement_id=row.pk,
            ).count(),
            User.objects.filter(is_active=True).count(),
        )
