"""账号彻底删除（ADR-0052）：物理删除 + 内容保留/清除两种模式 + 审计与保护规则。"""
import os
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from messaging.models import Conversation, Message
from news.models import News

from .hard_delete import (
    MODE_KEEP,
    MODE_PURGE,
    HardDeleteError,
    can_hard_delete,
    hard_delete_account,
)
from .models import (
    AccountDeletionLog,
    AccountIdentity,
    Profile,
    is_deleted_user,
)
from .testing import make_profile

TMP_ROOT = tempfile.mkdtemp(prefix="club-hard-delete-")


def tearDownModule():
    shutil.rmtree(TMP_ROOT, ignore_errors=True)


def make_user(username="alice", *, staff=False, superuser=False):
    user = User.objects.create_user(
        username=username, password="StrongPass123!", email=f"{username}@163.com",
    )
    if staff or superuser:
        user.is_staff = True
    if superuser:
        user.is_superuser = True
    if staff or superuser:
        user.save(update_fields=["is_staff", "is_superuser"])
    return user


@override_settings(
    MEDIA_ROOT=os.path.join(TMP_ROOT, "media"),
    PRIVATE_MEDIA_ROOT=os.path.join(TMP_ROOT, "private_media"),
)
class HardDeleteTest(TestCase):
    def setUp(self):
        self.admin = make_user("ops", staff=True)
        self.target = make_user("alice")
        make_profile(
            user=self.target, real_name="张三", nickname="小张",
            identity="student", bio="自我介绍",
        )
        avatar = self.target.profile
        avatar.avatar.save("avatar.png", ContentFile(b"avatar-bytes"), save=True)
        self.avatar_name = avatar.avatar.name
        self.avatar_storage = avatar.avatar.storage

        self.news = News.objects.create(title="社团新闻", author=self.target)
        self.peer = make_user("bob")
        self.conversation = Conversation.objects.create()
        self.conversation.participants.add(self.target, self.peer)
        self.message = Message.objects.create(
            conversation=self.conversation, sender=self.target, content="你好",
        )

    def test_keep_mode_moves_content_to_tombstone(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = hard_delete_account(
                self.target, actor=self.admin, mode=MODE_KEEP, reason="冒用他人身份",
            )

        self.assertFalse(User.objects.filter(pk=result.target_id).exists())
        self.assertFalse(Profile.objects.filter(user_id=result.target_id).exists())
        self.assertFalse(AccountIdentity.objects.filter(user_id=result.target_id).exists())

        self.news.refresh_from_db()
        self.assertEqual(self.news.author_id, result.tombstone_id)
        self.assertTrue(is_deleted_user(self.news.author))
        self.assertTrue(self.news.author.username.startswith("deleted_"))
        self.assertFalse(self.news.author.is_active)

        self.message.refresh_from_db()
        self.assertEqual(self.message.sender_id, result.tombstone_id)
        self.assertTrue(Conversation.objects.filter(pk=self.conversation.pk).exists())
        self.assertEqual(
            list(self.conversation.participants.values_list("username", flat=True)),
            ["bob"],
        )

        # 头像文件在提交后删除
        self.assertFalse(self.avatar_storage.exists(self.avatar_name))

        audit = AccountDeletionLog.objects.get(pk=result.audit_id)
        self.assertEqual(audit.target_username, "alice")
        self.assertEqual(audit.target_id, result.target_id)
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(audit.actor_username, "ops")
        self.assertEqual(audit.mode, MODE_KEEP)
        self.assertEqual(audit.reason, "冒用他人身份")

    def test_purge_mode_deletes_content_and_files(self):
        self.news.cover_image.save("cover.png", ContentFile(b"cover-bytes"), save=True)
        cover_name = self.news.cover_image.name
        cover_storage = self.news.cover_image.storage
        news_pk = self.news.pk

        with self.captureOnCommitCallbacks(execute=True):
            result = hard_delete_account(
                self.target, actor=self.admin, mode=MODE_PURGE,
            )

        self.assertFalse(User.objects.filter(pk=result.target_id).exists())
        self.assertFalse(News.objects.filter(pk=news_pk).exists())
        self.assertFalse(Message.objects.filter(sender_id=result.target_id).exists())
        self.assertFalse(cover_storage.exists(cover_name))
        self.assertFalse(self.avatar_storage.exists(self.avatar_name))
        self.assertIsNone(result.tombstone_id)

        audit = AccountDeletionLog.objects.get(pk=result.audit_id)
        self.assertEqual(audit.mode, MODE_PURGE)

    def test_self_delete_is_forbidden(self):
        with self.assertRaises(HardDeleteError) as ctx:
            hard_delete_account(self.admin, actor=self.admin, mode=MODE_KEEP)
        self.assertEqual(ctx.exception.reason, "hard_delete_forbidden")
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_admin_cannot_delete_admin_but_superuser_can(self):
        peer_admin = make_user("ops2", staff=True)
        allowed, why = can_hard_delete(self.admin, peer_admin)
        self.assertFalse(allowed)
        self.assertIn("超级管理员", why)

        root = make_user("root", superuser=True)
        allowed, _why = can_hard_delete(root, peer_admin)
        self.assertTrue(allowed)

    def test_last_superuser_is_protected(self):
        root = make_user("root", superuser=True)
        allowed, why = can_hard_delete(None, root)
        self.assertFalse(allowed)
        self.assertIn("最后一个", why)
        with self.assertRaises(HardDeleteError):
            hard_delete_account(root, actor=None, mode=MODE_KEEP)

    def test_non_staff_actor_is_forbidden(self):
        allowed, _why = can_hard_delete(self.peer, self.target)
        self.assertFalse(allowed)
        with self.assertRaises(HardDeleteError):
            hard_delete_account(self.target, actor=self.peer, mode=MODE_KEEP)

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(HardDeleteError) as ctx:
            hard_delete_account(self.target, actor=self.admin, mode="nuke")
        self.assertEqual(ctx.exception.reason, "invalid_mode")
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())


@override_settings(
    MEDIA_ROOT=os.path.join(TMP_ROOT, "media"),
    PRIVATE_MEDIA_ROOT=os.path.join(TMP_ROOT, "private_media"),
)
class HardDeleteAdminActionTest(TestCase):
    def setUp(self):
        self.root = make_user("root", superuser=True)
        self.target = make_user("alice")
        self.url = reverse("admin:auth_user_changelist")
        self.client.force_login(self.root)

    def _payload(self, **extra):
        data = {
            "action": "force_delete_accounts",
            "_selected_action": [str(self.target.pk)],
        }
        data.update(extra)
        return data

    def test_confirmation_page_then_delete(self):
        resp = self.client.post(self.url, self._payload())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "强制彻底删除账号")
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())

        resp = self.client.post(
            self.url,
            self._payload(
                post="yes", confirm="彻底删除", mode=MODE_KEEP, reason="测试",
            ),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())
        self.assertEqual(AccountDeletionLog.objects.count(), 1)

    def test_wrong_confirmation_text_keeps_account(self):
        resp = self.client.post(
            self.url, self._payload(post="yes", confirm="删除", mode=MODE_KEEP),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())
        self.assertEqual(AccountDeletionLog.objects.count(), 0)


@override_settings(
    MEDIA_ROOT=os.path.join(TMP_ROOT, "media"),
    PRIVATE_MEDIA_ROOT=os.path.join(TMP_ROOT, "private_media"),
)
class HardDeleteCommandTest(TestCase):
    def test_requires_yes_and_then_deletes(self):
        target = make_user("alice")

        call_command("hard_delete_account", "alice")
        self.assertTrue(User.objects.filter(pk=target.pk).exists())
        self.assertEqual(AccountDeletionLog.objects.count(), 0)

        call_command("hard_delete_account", str(target.pk), yes=True, reason="应急")
        self.assertFalse(User.objects.filter(pk=target.pk).exists())
        audit = AccountDeletionLog.objects.get()
        self.assertEqual(audit.actor_username, "cli")
        self.assertEqual(audit.reason, "应急")

        with self.assertRaises(CommandError):
            call_command("hard_delete_account", "alice", yes=True)
