"""认证模型单元 + 迁移默认信任（ADR-0006）+ 后台委任通道（ADR-0013）。

- ``is_verified``：纯计算（任一通道 approved 即真；匿名 / 无行 / pending / rejected ⇒ 假）。
  不读 ``is_staff`` / ``is_superuser``；委任走通道行。
- ``IsVerified`` 门禁：只读 ``is_verified``；超管无委任行亦不放行（认证轴无逃生舱）。
- 迁移：存量账号默认信任（旧布尔为真或无 profile ⇒ 造 manual approved 行）。
"""
from datetime import timedelta

from django.contrib.auth.models import AnonymousUser, User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import Verification, is_verified
from accounts.permissions import IsVerified


class IsVerifiedComputationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")

    def test_anonymous_not_verified(self):
        self.assertFalse(is_verified(AnonymousUser()))

    def test_no_rows_not_verified(self):
        self.assertFalse(is_verified(self.user))

    def test_pending_only_not_verified(self):
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL, status=Verification.STATUS_PENDING,
            identifier="u@e.com",
        )
        self.assertFalse(is_verified(self.user))

    def test_rejected_only_not_verified(self):
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_REJECTED,
        )
        self.assertFalse(is_verified(self.user))

    def test_approved_email_verified(self):
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL, status=Verification.STATUS_APPROVED,
            identifier="u@e.com",
        )
        self.assertTrue(is_verified(self.user))

    def test_approved_manual_verified(self):
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_APPROVED,
        )
        self.assertTrue(is_verified(self.user))

    def test_any_approved_suffices(self):
        # 一个 rejected + 一个 approved ⇒ 已认证（any-of）
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_REJECTED,
        )
        Verification.objects.create(
            user=self.user, channel=Verification.CHANNEL_EMAIL, status=Verification.STATUS_APPROVED,
            identifier="u@e.com",
        )
        self.assertTrue(is_verified(self.user))

    def test_is_verified_pure_no_superuser_special_case(self):
        # 纯计算不读标志位：超级用户若无 approved 行 ⇒ 未认证
        # 委任通道会在 save 时自动建行，这里删掉以钉死「函数不读 is_superuser」。
        self.user.is_superuser = True
        self.user.save()
        Verification.objects.filter(
            user=self.user, channel=Verification.CHANNEL_APPOINTMENT,
        ).delete()
        self.assertFalse(is_verified(self.user))


class IsVerifiedGateTest(TestCase):
    """写门禁只读 is_verified（ADR-0013）：委任通道使职员/超管通过；无行则拒，无标志位逃生舱。"""

    def test_superuser_blocked_without_appointment_row(self):
        u = User.objects.create_superuser(username="root", password="p")
        Verification.objects.filter(user=u, channel=Verification.CHANNEL_APPOINTMENT).delete()
        req = RequestFactory().post("/")
        req.user = u
        self.assertFalse(IsVerified().has_permission(req, None))

    def test_superuser_allowed_via_appointment_channel(self):
        u = User.objects.create_superuser(username="root", password="p")
        req = RequestFactory().post("/")
        req.user = u
        self.assertTrue(is_verified(u))
        self.assertTrue(IsVerified().has_permission(req, None))

    def test_normal_user_blocked_without_verification(self):
        u = User.objects.create_user(username="u", password="p")
        req = RequestFactory().post("/")
        req.user = u
        self.assertFalse(IsVerified().has_permission(req, None))

    def test_verified_user_allowed(self):
        u = User.objects.create_user(username="u", password="p")
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_APPROVED
        )
        req = RequestFactory().post("/")
        req.user = u
        self.assertTrue(IsVerified().has_permission(req, None))

    def test_staff_blocked_without_appointment_row(self):
        # 标志位不是认证逃生舱：删委任行后写动作仍拒（ADR-0013）
        u = User.objects.create_user(username="st", password="p", is_staff=True)
        Verification.objects.filter(user=u, channel=Verification.CHANNEL_APPOINTMENT).delete()
        req = RequestFactory().post("/")
        req.user = u
        self.assertFalse(IsVerified().has_permission(req, None))

    def test_staff_allowed_via_appointment_channel(self):
        u = User.objects.create_user(username="st", password="p", is_staff=True)
        req = RequestFactory().post("/")
        req.user = u
        self.assertTrue(is_verified(u))
        self.assertTrue(IsVerified().has_permission(req, None))


class VerificationDefaultTrustMigrationTest(TransactionTestCase):
    """迁移 0004 默认信任：存量账号（旧布尔为真或无 profile）⇒ 造 manual approved 行。

    用 TransactionTestCase：迁移 DDL 在 SQLite 下须在外层事务之外执行（TestCase 把整测
    包进单事务，与 schema_editor 的 FK 检查开关冲突）。
    """

    migrate_from = [("accounts", "0003_profile_email_verified_profile_identity_and_more")]
    migrate_to = [("accounts", "0004_remove_profile_email_verified_and_more")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        executor.migrate(self.migrate_from)
        self._seed_pre_feature_users(old_apps)
        executor.loader.build_graph()
        executor.migrate(self.migrate_to)
        self.apps_after = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        """把**所有 app** 迁回最新节点（否则会污染后续测试）。

        本类把 schema 停在 accounts/0004；TransactionTestCase 不回收 DDL，后续同类测试（也
        不回滚）只要碰到 0005 之后的列就会炸——例如删委任行时 collector 必须读回
        ``accounts_verification``（含 ``expires_at``）。

        **必须恢复到全图叶子，而不是 ``leaf_nodes("accounts")``。** ``setUp`` 里
        ``executor.migrate(migrate_from)`` 回退 accounts 时，Django 会连带 unapply
        依赖它的其他 app 迁移；只恢复 accounts 会把那些 app 留在旧 schema 上，
        后续测试报 ``no such column``（2026-10 B1 加 ``messaging_commentthread.target_id``
        时暴露：单独跑 messaging 绿、跑完本文件再跑就红）。
        """
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _seed_pre_feature_users(self, apps):
        User = apps.get_model("auth", "User")
        Profile = apps.get_model("accounts", "Profile")
        # 1) 有 profile、旧布尔默认为真（信任态）
        trusted = User.objects.create_user(username="legacy", password="p")
        Profile.objects.create(user=trusted)
        # 2) 无 profile（懒创建）——旧逻辑亦视为信任
        User.objects.create_user(username="noprofile", password="p")
        # 3) 显式未认证的自助注册账号（旧 register 曾设两布尔 False）——不应被信任
        unverified = User.objects.create_user(username="selfreg", password="p")
        Profile.objects.create(user=unverified, identity_verified=False, email_verified=False)

    def test_trusted_profile_user_becomes_verified(self):
        Verification = self.apps_after.get_model("accounts", "Verification")
        User = self.apps_after.get_model("auth", "User")
        u = User.objects.get(username="legacy")
        self.assertTrue(
            Verification.objects.filter(user=u, channel="manual", status="approved").exists()
        )

    def test_no_profile_user_becomes_verified(self):
        Verification = self.apps_after.get_model("accounts", "Verification")
        User = self.apps_after.get_model("auth", "User")
        u = User.objects.get(username="noprofile")
        self.assertTrue(
            Verification.objects.filter(user=u, channel="manual", status="approved").exists()
        )

    def test_explicitly_unverified_user_not_trusted(self):
        Verification = self.apps_after.get_model("accounts", "Verification")
        User = self.apps_after.get_model("auth", "User")
        u = User.objects.get(username="selfreg")
        self.assertFalse(Verification.objects.filter(user=u).exists())


# 通道对象的字段键集（前后端契约，#36）：与前端 VerificationPanel 的 VERIFICATION_CARD_FIELDS 对齐。
VERIFICATION_CARD_FIELDS = {"channel", "status", "identifier", "verified_at"}


class VerificationStatusEndpointTest(TestCase):
    """GET /auth/verification/（#36）：各通道当前状态 + 总 is_verified，数据驱动面板铺卡。"""

    URL = "/auth/verification/"

    def _get(self, user):
        c = Client()
        c.force_login(user)
        return c.get(self.URL)

    def test_requires_login(self):
        self.assertEqual(Client().get(self.URL).status_code, 302)

    def test_unverified_user_all_channels_none(self):
        u = User.objects.create_user(username="u", password="p")
        data = self._get(u).json()
        self.assertFalse(data["is_verified"])
        channels = {c["channel"]: c for c in data["channels"]}
        self.assertEqual(set(channels), {"appointment", "email", "manual", "authcode"})  # 每定义通道一卡
        self.assertEqual(channels["appointment"]["status"], "none")
        self.assertEqual(channels["email"]["status"], "none")
        self.assertEqual(channels["manual"]["status"], "none")
        self.assertEqual(channels["authcode"]["status"], "none")

    def test_email_pending_shown_not_verified(self):
        u = User.objects.create_user(username="u", password="p")
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING, identifier="u@e.com",
        )
        data = self._get(u).json()
        self.assertFalse(data["is_verified"])  # pending 不算已认证
        email = {c["channel"]: c for c in data["channels"]}["email"]
        self.assertEqual(email["status"], "pending")
        self.assertEqual(email["identifier"], "u@e.com")

    def test_manual_approved_is_verified(self):
        u = User.objects.create_user(username="u", password="p")
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_MANUAL,
            status=Verification.STATUS_APPROVED, verified_at=timezone.now(),
        )
        data = self._get(u).json()
        self.assertTrue(data["is_verified"])
        manual = {c["channel"]: c for c in data["channels"]}["manual"]
        self.assertEqual(manual["status"], "approved")
        self.assertIsNotNone(manual["verified_at"])

    def test_manual_rejected_shown(self):
        u = User.objects.create_user(username="u", password="p")
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_REJECTED,
        )
        data = self._get(u).json()
        self.assertFalse(data["is_verified"])
        manual = {c["channel"]: c for c in data["channels"]}["manual"]
        self.assertEqual(manual["status"], "rejected")

    def test_channels_in_defined_order(self):
        u = User.objects.create_user(username="u", password="p")
        channels = [c["channel"] for c in self._get(u).json()["channels"]]
        self.assertEqual(channels, ["appointment", "email", "manual", "authcode"])  # CHANNELS 定义序

    def test_channel_object_keyset(self):
        # 钉死通道对象键集（前后端契约的「后端半」；前端半见 VerificationPanelContractTest）
        u = User.objects.create_user(username="u", password="p")
        channels = self._get(u).json()["channels"]
        for card in channels:
            self.assertEqual(set(card.keys()), VERIFICATION_CARD_FIELDS)


class SingleVerificationPathTest(TestCase):
    """单一认证路径：任一通道认证通过后，其余通道派生为 ``not_required``（无需再次认证）。

    该状态只在读取时计算、不落库：认证过期后账号回落访客，其余通道必须恢复真实状态
    （仍可重新申请），否则用户会被永久锁在「无需再次认证」里。
    """

    URL = "/auth/verification/"

    def _status(self, user):
        c = Client()
        c.force_login(user)
        data = c.get(self.URL).json()
        return data, {ch["channel"]: ch for ch in data["channels"]}

    def test_manual_approved_closes_other_channels(self):
        u = User.objects.create_user(username="u", password="p")
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_MANUAL,
            status=Verification.STATUS_APPROVED, verified_at=timezone.now(),
        )
        data, channels = self._status(u)
        self.assertTrue(data["is_verified"])
        self.assertEqual(channels["manual"]["status"], "approved")
        self.assertEqual(channels["email"]["status"], "not_required")
        self.assertEqual(channels["authcode"]["status"], "not_required")
        # 委任卡后端仍每通道一卡（键集契约不变），派生态交给前端决定不铺卡。
        self.assertEqual(channels["appointment"]["status"], "not_required")

    def test_email_approved_closes_other_channels(self):
        u = User.objects.create_user(username="u", password="p")
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_EMAIL, status=Verification.STATUS_APPROVED,
            identifier="u@163.com", verified_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        data, channels = self._status(u)
        self.assertTrue(data["is_verified"])
        self.assertEqual(channels["email"]["status"], "approved")
        self.assertEqual(channels["email"]["identifier"], "u@163.com")  # 标识仍下发（登录 / 找回密码展示）
        self.assertEqual(channels["manual"]["status"], "not_required")
        self.assertEqual(channels["authcode"]["status"], "not_required")

    def test_rejected_channel_masked_when_verified(self):
        """已认证时，其余通道的历史状态（驳回 / 审核中）也收口为「无需再次认证」。"""
        u = User.objects.create_user(username="u", password="p")
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_EMAIL, status=Verification.STATUS_APPROVED,
            identifier="u@163.com", verified_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_REJECTED,
        )
        channels = self._status(u)[1]
        self.assertEqual(channels["manual"]["status"], "not_required")

    def test_expired_verification_does_not_lock_other_channels(self):
        """认证过期 → 账号回落访客，其余通道恢复真实状态，仍可重新申请。"""
        u = User.objects.create_user(username="u", password="p")
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_MANUAL, status=Verification.STATUS_APPROVED,
            verified_at=timezone.now() - timedelta(days=400),
            expires_at=timezone.now() - timedelta(days=1),
        )
        data, channels = self._status(u)
        self.assertFalse(data["is_verified"])
        self.assertEqual(channels["manual"]["status"], "approved")  # 历史记录保留
        self.assertEqual(channels["email"]["status"], "none")
        self.assertEqual(channels["authcode"]["status"], "none")


class VerificationPanelContractTest(TestCase):
    """前后端键集契约（#36）：状态端点通道集 + 通道对象键集 == 前端 VerificationPanel 预期。"""

    def test_backend_keyset_matches_frontend_panel(self):
        import re
        from pathlib import Path

        ts_path = (
            Path(__file__).resolve().parents[1]
            / "frontend" / "src" / "components" / "profile" / "VerificationPanel.tsx"
        )
        src = ts_path.read_text(encoding="utf-8")

        # 前端 VERIFICATION_CHANNELS = ["appointment", "email", "manual", "authcode"]
        ch_match = re.search(r"VERIFICATION_CHANNELS\s*=\s*\[([^\]]*)\]", src)
        self.assertIsNotNone(ch_match, "前端未定义 VERIFICATION_CHANNELS")
        fe_channels = set(re.findall(r'"([a-z]+)"', ch_match.group(1)))

        # 前端 VERIFICATION_CARD_FIELDS = ["channel", "status", ...]
        fd_match = re.search(r"VERIFICATION_CARD_FIELDS\s*=\s*\[([^\]]*)\]", src)
        self.assertIsNotNone(fd_match, "前端未定义 VERIFICATION_CARD_FIELDS")
        fe_fields = set(re.findall(r'"([a-z_]+)"', fd_match.group(1)))

        u = User.objects.create_user(username="u", password="p")
        c = Client()
        c.force_login(u)
        data = c.get("/auth/verification/").json()
        be_channels = {ch["channel"] for ch in data["channels"]}
        be_fields = set(data["channels"][0].keys())

        self.assertEqual(fe_channels, be_channels, f"通道集漂移：后端={sorted(be_channels)} 前端={sorted(fe_channels)}")
        self.assertEqual(fe_fields, be_fields, f"通道对象键集漂移：后端={sorted(be_fields)} 前端={sorted(fe_fields)}")


class AppointmentChannelTest(TestCase):
    """后台委任通道（ADR-0013）：is_staff / is_superuser ⇒ approved 行；撤销则删行。"""

    def test_ordinary_user_has_no_appointment_row(self):
        u = User.objects.create_user(username="u", password="p")
        self.assertFalse(
            Verification.objects.filter(user=u, channel=Verification.CHANNEL_APPOINTMENT).exists()
        )
        self.assertFalse(is_verified(u))

    def test_staff_save_grants_approved_appointment(self):
        u = User.objects.create_user(username="st", password="p")
        u.is_staff = True
        u.save()
        row = Verification.objects.get(user=u, channel=Verification.CHANNEL_APPOINTMENT)
        self.assertEqual(row.status, Verification.STATUS_APPROVED)
        self.assertEqual(row.identifier, "staff")
        self.assertIsNotNone(row.verified_at)
        self.assertIsNone(row.verified_by_id)
        self.assertTrue(is_verified(u))

    def test_superuser_save_grants_superuser_identifier(self):
        u = User.objects.create_superuser(username="root", password="p")
        row = Verification.objects.get(user=u, channel=Verification.CHANNEL_APPOINTMENT)
        self.assertEqual(row.status, Verification.STATUS_APPROVED)
        self.assertEqual(row.identifier, "superuser")
        self.assertTrue(is_verified(u))

    def test_demote_superuser_to_staff_keeps_appointment(self):
        u = User.objects.create_superuser(username="root", password="p")
        u.is_superuser = False
        u.save()  # create_superuser 默认 is_staff=True，仍算委任
        row = Verification.objects.get(user=u, channel=Verification.CHANNEL_APPOINTMENT)
        self.assertEqual(row.identifier, "staff")
        self.assertTrue(is_verified(u))

    def test_revoke_staff_deletes_appointment_unverified(self):
        u = User.objects.create_user(username="st", password="p", is_staff=True)
        u.is_staff = False
        u.save()
        self.assertFalse(
            Verification.objects.filter(user=u, channel=Verification.CHANNEL_APPOINTMENT).exists()
        )
        self.assertFalse(is_verified(u))

    def test_revoke_keeps_other_approved_channels(self):
        u = User.objects.create_user(username="st", password="p", is_staff=True)
        Verification.objects.create(
            user=u, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_APPROVED, identifier="st@e.com",
        )
        u.is_staff = False
        u.save()
        self.assertFalse(
            Verification.objects.filter(user=u, channel=Verification.CHANNEL_APPOINTMENT).exists()
        )
        self.assertTrue(is_verified(u))  # email 仍 approved

    def test_idempotent_resave_does_not_reset_verified_at(self):
        u = User.objects.create_user(username="st", password="p", is_staff=True)
        row = Verification.objects.get(user=u, channel=Verification.CHANNEL_APPOINTMENT)
        first_at = row.verified_at
        u.save()
        row.refresh_from_db()
        self.assertEqual(row.verified_at, first_at)


class AppointmentStatusEndpointTest(TestCase):
    """GET /auth/verification/ 对委任通道：普通人 none；委任后 approved + identifier。"""

    URL = "/auth/verification/"

    def _get(self, user):
        c = Client()
        c.force_login(user)
        return c.get(self.URL)

    def test_staff_appointment_approved(self):
        u = User.objects.create_user(username="st", password="p", is_staff=True)
        data = self._get(u).json()
        self.assertTrue(data["is_verified"])
        card = {c["channel"]: c for c in data["channels"]}["appointment"]
        self.assertEqual(card["status"], "approved")
        self.assertEqual(card["identifier"], "staff")
        self.assertIsNotNone(card["verified_at"])

    def test_superuser_appointment_identifier(self):
        u = User.objects.create_superuser(username="root", password="p")
        card = {c["channel"]: c for c in self._get(u).json()["channels"]}["appointment"]
        self.assertEqual(card["status"], "approved")
        self.assertEqual(card["identifier"], "superuser")
