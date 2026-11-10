"""``lifecycle_q`` / ``identity_q`` 的语义测试（B4 PR 3b2 之后）。

## 这批测试的历史

PR 2b（#220）时它们叫「等价性测试」：同时跑「旧列查询」和「新表查询」，断言结果集
完全相同。那时旧列还在、新表可能缺行，两条分支都要覆盖。

PR 3b2 删掉旧列后**没有「旧写法」可比了**——等价性测试的对照物消失了。所以改成
语义测试：直接断言新查询在各种用户形态下的行为。

## 仍然要守住的边界

1. **缺行的用户会被排除**（INNER JOIN 语义）。这是有意的：缺行属异常状态，
   两道保险保证不会发生（``0035`` 迁移补齐存量、``Profile.save()`` 补新增）。
   如果这里变成「缺行也返回」，说明有人又加了回落——那会让「已注销用户突然出现」。
2. **结果集非空**。只断言「等于某个集合」不够，得确认那个集合里真的有预期的人，
   否则「全都返回空集」也能通过。
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import AccountIdentity, AccountLifecycle, Profile
from .queries import (
    deleted_q,
    expiry_disabled_q,
    identity_q,
    lifecycle_q,
    must_change_password_q,
    not_deleted_q,
)
from .testing import make_profile


def _user(username, *, is_active=True):
    return User.objects.create_user(username=username, password="x", is_active=is_active)


def _drop_split_rows(user):
    """制造「新表缺行」状态（模拟异常数据）。"""
    AccountIdentity.objects.filter(user=user).delete()
    AccountLifecycle.objects.filter(user=user).delete()


class LifecycleQueryTest(TestCase):
    def setUp(self):
        now = timezone.now()
        self.clean = _user("clean")
        make_profile(self.clean)

        self.deleted = _user("deleted", is_active=False)
        make_profile(self.deleted, deleted_at=now)

        self.expired = _user("expired", is_active=False)
        make_profile(self.expired, expiry_disabled_at=now)

        self.mcp = _user("mcp")
        make_profile(self.mcp, must_change_password=True)

        # 新表缺行（异常状态）
        self.missing = _user("missing")
        Profile.objects.create(user=self.missing)
        _drop_split_rows(self.missing)

    def _ids(self, q):
        return set(Profile.objects.filter(q).values_list("user_id", flat=True))

    def test_not_deleted_excludes_deleted(self):
        ids = self._ids(not_deleted_q())
        self.assertIn(self.clean.pk, ids)
        self.assertIn(self.mcp.pk, ids)
        self.assertNotIn(self.deleted.pk, ids)

    def test_deleted_returns_only_deleted(self):
        self.assertEqual(self._ids(deleted_q()), {self.deleted.pk})

    def test_expiry_disabled_returns_only_expired(self):
        self.assertEqual(self._ids(expiry_disabled_q()), {self.expired.pk})

    def test_must_change_password_returns_only_flagged(self):
        self.assertEqual(self._ids(must_change_password_q()), {self.mcp.pk})

    def test_missing_split_rows_are_excluded(self):
        """缺行 = 异常状态。

        ``deleted_q`` / ``expiry_disabled_q`` / ``must_change_password_q`` 走 INNER
        JOIN，缺行用户被排除。``not_deleted_q`` 例外——它查 ``isnull=True``，Django
        会改用 LEFT JOIN，缺行用户**会**被包含。这是安全的方向（不把用户藏起来），
        不要「修正」成排除。
        """
        for q in (deleted_q(), expiry_disabled_q(), must_change_password_q()):
            self.assertNotIn(self.missing.pk, self._ids(q))
        self.assertIn(self.missing.pk, self._ids(not_deleted_q()))

    def test_lifecycle_q_rejects_bad_args(self):
        with self.assertRaises(ValueError):
            lifecycle_q("deleted_at")
        with self.assertRaises(ValueError):
            lifecycle_q("deleted_at", value=1, isnull=True)


class IdentityQueryTest(TestCase):
    def setUp(self):
        self.alice = _user("alice")
        make_profile(self.alice, real_name="张三", identity="student")

        self.bob = _user("bob")
        make_profile(self.bob, real_name="李四", identity="teacher")

    def _ids(self, q):
        return set(Profile.objects.filter(q).values_list("user_id", flat=True))

    def test_exact_match(self):
        self.assertEqual(self._ids(identity_q("real_name", iexact="张三")), {self.alice.pk})

    def test_no_match_returns_empty(self):
        self.assertEqual(self._ids(identity_q("real_name", iexact="王五")), set())

    def test_identity_field_also_queryable(self):
        self.assertEqual(self._ids(identity_q("identity", exact="teacher")), {self.bob.pk})

    def test_lookup_needs_separator(self):
        """回归：``real_name`` + ``exact`` 曾拼成 ``real_nameexact``，只在执行时炸。"""
        # 不抛 FieldError 即通过
        self.assertEqual(self._ids(identity_q("real_name", exact="张三")), {self.alice.pk})

    def test_rejects_empty_lookup(self):
        with self.assertRaises(ValueError):
            identity_q("real_name")
