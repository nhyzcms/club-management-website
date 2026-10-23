"""账号注销（ADR-0027）：软删除 + 敏感信息清除 + 注销态展示。

覆盖：三重确认（安全验证 / 逐字确认 / 密码）、敏感字段与文件清除、
账号编码 / 真实姓名 / 社员身份保留、私信历史可读但不可再发、用户搜索与
个人主页的注销态表现。
"""
import json
import os
import shutil
import tempfile
from datetime import date

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from accounts import stepup
from accounts.deletion import AccountDeletionError, delete_account
from accounts.models import (
    DELETED_ACCOUNT_LABEL,
    IdentityProof,
    MemberIdentity,
    Profile,
    SecurityQuestion,
    StepUpEmailCode,
    StepUpEvent,
    UserSession,
    Verification,
)
from accounts.test_helpers import grant_verification
from messaging.models import (
    Conversation,
    Message,
    MessageReadStatus,
    Notification,
    NotificationSubscription,
)
from tasks.serializers import SimpleUserSerializer

TMP_ROOT = tempfile.mkdtemp(prefix="club-account-deletion-")


def tearDownModule():
    shutil.rmtree(TMP_ROOT, ignore_errors=True)


def make_user(username="alice", password="StrongPass123!", email="alice@163.com"):
    user = User.objects.create_user(username=username, password=password, email=email)
    Profile.objects.create(
        user=user,
        real_name="张三",
        nickname="小张",
        identity="student",
        bio="自我介绍",
        birthday=date(2008, 1, 1),
        gender="M",
    )
    return user


@override_settings(
    MEDIA_ROOT=os.path.join(TMP_ROOT, "media"),
    PRIVATE_MEDIA_ROOT=os.path.join(TMP_ROOT, "private_media"),
)
class DeleteAccountApiTest(TestCase):
    def setUp(self):
        self.user = make_user()
        self.profile = self.user.profile
        self.profile.avatar.save("avatar.png", ContentFile(b"avatar-bytes"), save=True)
        self.avatar_name = self.profile.avatar.name

        # 两条验证通道：邮箱（identifier = 邮箱原文）与人工（证据材料）。
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_APPROVED, identifier="alice@163.com",
        )
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_MANUAL,
            status=Verification.STATUS_APPROVED,
        )
        proof = IdentityProof(user=self.user)
        proof.file.save("proof.png", ContentFile(b"proof-bytes"), save=True)
        self.proof_name = proof.file.name
        self.proof_storage = proof.file.storage

        # 登录设备 / 安全验证残留 / 站内通知。
        UserSession.objects.create(user=self.user, session_key="s" * 40)
        SecurityQuestion.objects.create(
            user=self.user, question_key="birth_city", question_text="你出生的城市是？",
            answer_hash="x",
        )
        StepUpEmailCode.objects.create(
            user=self.user, code_hash="x", sent_to="alice@163.com",
            expires_at=self.user.date_joined,
        )
        StepUpEvent.objects.create(user=self.user, scope="change_password", method="email", result="ok")
        Notification.objects.create(recipient=self.user, category=Notification.CATEGORY_DM, event="new_message")
        NotificationSubscription.objects.create(
            user=self.user, source_key="dm", channel_key="inapp",
        )

        # 社员身份（名册行）：注销后必须原样保留（含识别码与绑定关系）。
        self.member = MemberIdentity.objects.create(
            name="张三", class_no="1", student_no="2008001",
            admit_year=2024, cohort=2024, code="NH2024001",
            user=self.user, bind_method=MemberIdentity.BIND_SELF,
        )

        self.client.force_login(self.user)

    def _post(self, payload, grant=None):
        headers = {"HTTP_X_STEPUP_GRANT": grant} if grant else {}
        return self.client.post(
            "/auth/account/delete/",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

    def _payload(self, password="StrongPass123!", confirm="注销账号"):
        return {"password": password, "confirm": confirm}

    def test_requires_step_up_when_method_available(self):
        resp = self._post(self._payload())
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "step_up_required")
        # 未真正注销
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertIsNone(self.user.profile.deleted_at)

    def test_wrong_password_or_confirmation_is_rejected(self):
        grant = stepup.issue_grant(self.user, "delete_account")
        resp = self._post(self._payload(confirm="注销"), grant=grant)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["reason"], "confirmation_required")

        resp = self._post(self._payload(password="wrong-pass"), grant=grant)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["reason"], "password_incorrect")

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_delete_scrubs_sensitive_data_and_keeps_identity(self):
        user_id = self.user.pk
        grant = stepup.issue_grant(self.user, "delete_account")
        resp = self._post(self._payload(), grant=grant)
        self.assertEqual(resp.status_code, 200)

        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.member.refresh_from_db()

        # 账号本体：停用 + 邮箱 / 密码清除；编号（pk / username）不变。
        self.assertFalse(self.user.is_active)
        self.assertEqual(self.user.id, user_id)
        self.assertEqual(self.user.username, "alice")
        self.assertEqual(self.user.email, "")
        self.assertFalse(self.user.check_password("StrongPass123!"))
        self.assertIsNotNone(self.profile.deleted_at)

        # 资料：真实姓名 / 昵称保留（后台审计），其余敏感字段清空。
        self.assertEqual(self.profile.real_name, "张三")
        self.assertEqual(self.profile.nickname, "小张")
        self.assertEqual(self.profile.bio, "")
        self.assertIsNone(self.profile.birthday)
        self.assertEqual(self.profile.gender, "")
        self.assertFalse(self.profile.avatar)

        # 文件：头像与身份证明材料都已从存储删除。
        self.assertFalse(self.profile.avatar.storage.exists(self.avatar_name))
        self.assertFalse(self.proof_storage.exists(self.proof_name))
        self.assertEqual(IdentityProof.objects.filter(user_id=user_id).count(), 0)

        # 验证通道 / 会话 / 安全验证残留 / 通知全部清除。
        self.assertEqual(Verification.objects.filter(user_id=user_id).count(), 0)
        self.assertEqual(UserSession.objects.filter(user_id=user_id).count(), 0)
        self.assertEqual(SecurityQuestion.objects.filter(user_id=user_id).count(), 0)
        self.assertEqual(StepUpEmailCode.objects.filter(user_id=user_id).count(), 0)
        self.assertEqual(StepUpEvent.objects.filter(user_id=user_id).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient_id=user_id).count(), 0)
        self.assertEqual(NotificationSubscription.objects.filter(user_id=user_id).count(), 0)

        # 社员身份（名册行 + 识别码 + 绑定）保留。
        self.assertEqual(self.member.code, "NH2024001")
        self.assertEqual(self.member.user_id, user_id)

        # 已登出：当前会话不再视为已登录。
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deleted_account_cannot_login(self):
        delete_account(self.user)
        self.client.logout()
        resp = self.client.post(
            "/auth/login/",
            data=json.dumps({"username": "alice", "password": "StrongPass123!"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_admin_accounts_are_protected(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        grant = stepup.issue_grant(self.user, "delete_account")
        resp = self._post(self._payload(), grant=grant)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "account_deletion_protected")

    def test_second_deletion_is_conflict(self):
        delete_account(self.user)
        # 注销后会话已失效（无法再走 API，302 登录跳转），故直接验证服务层幂等语义。
        with self.assertRaises(AccountDeletionError) as ctx:
            delete_account(self.user)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.reason, "account_already_deleted")

    def test_without_step_up_methods_password_is_enough(self):
        # 未认证邮箱、未设安全问题的账号仍可注销（否则会被永久挡住）。
        self.user.email = ""
        self.user.save(update_fields=["email"])
        SecurityQuestion.objects.filter(user=self.user).delete()
        resp = self._post(self._payload())
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_auto_match_skips_deleted_accounts(self):
        # 注销账号不再参与名册自动匹配：同名的新名册行必须保持未绑定（可被新人认领）。
        from accounts.member_roster import auto_match_identities

        delete_account(self.user)
        MemberIdentity.objects.filter(user_id=self.user.pk).update(user=None)
        row = MemberIdentity.objects.create(
            name="张三", admit_year=2026, cohort=2026, code="NH2026001",
        )
        auto_match_identities([row])
        row.refresh_from_db()
        self.assertIsNone(row.user_id)


@override_settings(
    MEDIA_ROOT=os.path.join(TMP_ROOT, "media"),
    PRIVATE_MEDIA_ROOT=os.path.join(TMP_ROOT, "private_media"),
)
class DeletedAccountVisibilityTest(TestCase):
    def setUp(self):
        self.deleted = make_user("ghost")
        delete_account(self.deleted)
        self.viewer = make_user("viewer")
        grant_verification(self.viewer)
        self.client.force_login(self.viewer)

    def test_simple_user_serializer_masks_deleted_account(self):
        data = SimpleUserSerializer(instance=User.objects.get(pk=self.deleted.pk)).data
        self.assertTrue(data["is_deleted"])
        self.assertEqual(data["nickname"], DELETED_ACCOUNT_LABEL)
        self.assertEqual(data["username"], "")
        self.assertIsNone(data["avatar"])

    def test_profile_page_returns_tombstone(self):
        resp = self.client.get(f"/auth/users/{self.deleted.pk}/profile/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["deleted"])
        self.assertEqual(data["user"]["id"], self.deleted.pk)
        self.assertEqual(data["user"]["username"], "")
        self.assertEqual(data["profile"]["nickname"], "")
        self.assertNotIn("permissions", data)

    def test_user_search_excludes_deleted_accounts(self):
        resp = self.client.get("/auth/users/", {"search": "ghost"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])

    def test_start_private_rejected(self):
        resp = self.client.post(
            "/messaging/conversations/start_private/",
            data=json.dumps({"user_id": self.deleted.pk}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("已注销", resp.json()["detail"])

    def test_history_is_readable_but_sending_is_blocked(self):
        conversation = Conversation.objects.create()
        conversation.participants.set([self.viewer, self.deleted])
        message = Message.objects.create(
            conversation=conversation, sender=self.deleted, content="历史消息",
        )
        MessageReadStatus.objects.create(message=message, user=self.viewer)

        resp = self.client.get(
            "/messaging/conversations/messages/", {"conversation_id": conversation.pk},
        )
        self.assertEqual(resp.status_code, 200)
        row = resp.json()["results"][0]
        self.assertEqual(row["sender"]["nickname"], DELETED_ACCOUNT_LABEL)
        self.assertTrue(row["sender"]["is_deleted"])
        self.assertEqual(row["content"], "历史消息")

        resp = self.client.post(
            f"/messaging/conversations/{conversation.pk}/send_message/",
            data=json.dumps({"content": "还能发吗"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("已注销", resp.json()["detail"])
        self.assertEqual(Message.objects.filter(conversation=conversation).count(), 1)
