"""``accounts/status.py: account_state()`` 的测试（B4）。

**这批测试要钉住的核心不是「四个状态各自对不对」**——那是显然的。要钉住的是
两条容易写错的：

1. **优先级**：注销用户的 ``is_active`` 通常也是 ``False``。若先判 ``is_active``，
   一个自己注销的人会被告知「账号已被管理员停用」。生产上确实存在这样的行。
2. **回落**：新表缺失时必须回落到 ``Profile``，否则一个已注销的账号会被判成
   「正常」——把不可用账号当可用，是最危险的方向。

**夹具约定（PR 2a 起）**：``Profile.objects.create()`` 会自动把 8 个字段同步到
``AccountIdentity`` / ``AccountLifecycle``（见 ``accounts/sync.py``）。所以这里
**不再手动建新表行**——那样会与双写撞 UNIQUE。需要「新表缺行」时，建完 Profile
再把新表行删掉；需要「两表不一致」时，用 ``.update()`` 改新表（``update`` 不触发
``save()``，不会回写 Profile）。
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import AccountIdentity, AccountLifecycle, Profile
from .testing import make_profile
from .status import (
    ACTIVE,
    ADMIN_EXPIRED,
    DELETED,
    UNVERIFIED_EXPIRED,
    account_state,
    is_usable,
)


def _user(username, *, is_active=True):
    return User.objects.create_user(username=username, password="x", is_active=is_active)


def _drop_split_rows(user):
    """制造「新表落后于 Profile」的状态（模拟 PR 1 之后、2a 之前的历史用户）。"""
    AccountIdentity.objects.filter(user=user).delete()
    AccountLifecycle.objects.filter(user=user).delete()


class AccountStateTest(TestCase):
    def test_active(self):
        user = _user("a")
        Profile.objects.create(user=user)
        self.assertEqual(account_state(user), (ACTIVE, ""))
        self.assertTrue(is_usable(user))

    def test_deleted(self):
        user = _user("b", is_active=False)
        make_profile(user=user, deleted_at=timezone.now())
        state, reason = account_state(user)
        self.assertEqual(state, DELETED)
        self.assertIn("注销", reason)
        self.assertFalse(is_usable(user))

    def test_unverified_expired(self):
        user = _user("c", is_active=False)
        make_profile(user=user, expiry_disabled_at=timezone.now())
        state, reason = account_state(user)
        self.assertEqual(state, UNVERIFIED_EXPIRED)
        self.assertIn("认证", reason)

    def test_admin_expired(self):
        user = _user("d", is_active=False)
        Profile.objects.create(user=user)
        state, reason = account_state(user)
        self.assertEqual(state, ADMIN_EXPIRED)
        self.assertIn("管理员", reason)

    def test_deleted_beats_admin_expired(self):
        """注销优先于「is_active=False」。

        生产实测：一个用户 is_active=False 且 deleted_at 非空。若判定顺序写反，
        他会被告知「已被管理员停用」——真相是他自己注销的。
        """
        user = _user("e", is_active=False)
        make_profile(user=user, deleted_at=timezone.now())
        self.assertEqual(account_state(user)[0], DELETED)

    def test_deleted_beats_unverified_expired(self):
        """注销也优先于超期停用（注销是用户主动行为，信息量更高）。"""
        user = _user("f", is_active=False)
        now = timezone.now()
        make_profile(user=user, deleted_at=now, expiry_disabled_at=now)
        self.assertEqual(account_state(user)[0], DELETED)

    def test_no_profile_no_lifecycle_still_answers(self):
        """两表都没有（迁移前的老账号 / 测试夹具）：不能抛异常。"""
        user = _user("i")
        self.assertEqual(account_state(user), (ACTIVE, ""))


class AccountIdentityModelTest(TestCase):
    def test_pending_card_no_defaults_empty(self):
        user = _user("k")
        row = AccountIdentity.objects.create(user=user)
        self.assertEqual(row.pending_card_no, "")

    def test_identity_choices_reused_from_profile(self):
        """choices 与 Profile 保持一致——PR 3 删 Profile 字段时要把 choices 搬过来。"""
        field = AccountIdentity._meta.get_field("identity")
        self.assertEqual(
            [c[0] for c in field.choices],
            [c[0] for c in Profile.IDENTITY_CHOICES],
        )
