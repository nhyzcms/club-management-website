"""``Profile.save()`` 双写测试（B4 PR 2a）。

**要钉住的是「新表不落后」**——PR 3 删旧列的前提是新表已经完整。任何一个写点
漏同步，删列时那部分数据就永久丢了。

反证：把 ``Profile.save()`` 里的 ``sync_from_profile(self)`` 删掉，
``test_new_profile_creates_split_rows`` 起全红。
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import AccountIdentity, AccountLifecycle, Profile
from .sync import backfill_all, sync_from_profile


def _user(username):
    return User.objects.create_user(username=username, password="x")


class ProfileSyncTest(TestCase):
    def test_new_profile_creates_split_rows(self):
        user = _user("a")
        Profile.objects.create(
            user=user, real_name="张三", identity="student", card_no="A123",
        )
        ident = AccountIdentity.objects.get(user=user)
        life = AccountLifecycle.objects.get(user=user)
        self.assertEqual(ident.real_name, "张三")
        self.assertEqual(ident.identity, "student")
        self.assertEqual(ident.pending_card_no, "A123")
        self.assertEqual(life.deleted_at, None)

    def test_field_change_propagates(self):
        user = _user("b")
        profile = Profile.objects.create(user=user, real_name="旧名", card_no="A1")
        profile.real_name = "新名"
        profile.card_no = "B2"
        profile.save()
        ident = AccountIdentity.objects.get(user=user)
        self.assertEqual(ident.real_name, "新名")
        self.assertEqual(ident.pending_card_no, "B2")

    def test_lifecycle_change_propagates(self):
        user = _user("c")
        profile = Profile.objects.create(user=user)
        now = timezone.now()
        profile.deleted_at = now
        profile.must_change_password = True
        profile.validity_notice_ack = "verified:2027"
        profile.save()
        life = AccountLifecycle.objects.get(user=user)
        self.assertEqual(life.deleted_at, now)
        self.assertTrue(life.must_change_password)
        self.assertEqual(life.validity_notice_ack, "verified:2027")

    def test_expiry_change_propagates(self):
        user = _user("d")
        profile = Profile.objects.create(user=user)
        now = timezone.now()
        profile.expiry_disabled_at = now
        profile.registration_deadline = now
        profile.save()
        life = AccountLifecycle.objects.get(user=user)
        self.assertEqual(life.expiry_disabled_at, now)
        self.assertEqual(life.registration_deadline, now)

    def test_sync_is_idempotent(self):
        """重复同步不产生第二行（OneToOne 的 update_or_create 语义）。"""
        user = _user("e")
        profile = Profile.objects.create(user=user, real_name="x")
        sync_from_profile(profile)
        sync_from_profile(profile)
        self.assertEqual(AccountIdentity.objects.filter(user=user).count(), 1)
        self.assertEqual(AccountLifecycle.objects.filter(user=user).count(), 1)

    def test_blank_values_become_empty_strings_not_null(self):
        """CharField 不允许 null；空值必须落成空串，否则 PG 会拒绝写入。"""
        user = _user("f")
        Profile.objects.create(user=user)
        ident = AccountIdentity.objects.get(user=user)
        self.assertEqual(ident.real_name, "")
        self.assertEqual(ident.pending_card_no, "")

    def test_backfill_all_covers_existing_profiles(self):
        """模拟 PR 1 之后、2a 之前创建的用户：新表缺行，backfill 补上。"""
        user = _user("g")
        profile = Profile.objects.create(user=user, real_name="补我")
        # 手动删掉双写产生的行，制造「落后」状态
        AccountIdentity.objects.filter(user=user).delete()
        AccountLifecycle.objects.filter(user=user).delete()
        self.assertFalse(AccountIdentity.objects.filter(user=user).exists())

        count = backfill_all()
        self.assertGreaterEqual(count, 1)
        self.assertEqual(AccountIdentity.objects.get(user=user).real_name, "补我")

    def test_account_state_sees_synced_data(self):
        """双写 + status.py 串起来：注销写入后 account_state 立刻反映。"""
        from .status import DELETED, account_state

        user = _user("h")
        profile = Profile.objects.create(user=user)
        self.assertEqual(account_state(user)[0], "active")
        profile.deleted_at = timezone.now()
        profile.save()
        user.refresh_from_db()
        self.assertEqual(account_state(user)[0], DELETED)
