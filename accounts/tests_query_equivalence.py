"""B4 PR 2b 的等价性测试：新表查询 vs 旧列查询，结果集必须完全相同。

## 为什么这批测试值得单独写

`deleted_at` 过滤写错的方向是「已注销用户突然能看到消息」，或者反过来
「正常用户从名册里消失」。两种都不会报错，只会静默错。

所以这里不只断言「两种写法相等」——**还要断言结果集非空、且特定的关键用户
在里面**。否则一个「两边都返回空集」的 bug 也能通过 `assertEqual`。

## 八种用户形态

| # | 新表 | 旧列 | 说明 |
|---|------|------|------|
| 1 | 有行 | 正常 | 当前主流 |
| 2 | 有行 | 已注销 | 当前主流 |
| 3 | **缺行** | 正常 | PR 1 之后、2a 之前的历史用户 |
| 4 | **缺行** | 已注销 | 同上，最容易漏 |
| 5 | 有行 | 超期停用 | |
| 6 | **缺行** | 超期停用 | |
| 7 | 有行 | 需改密 | |
| 8 | **缺行** | 需改密 | |

形态 3/4/6/8 是 INNER JOIN 写法会漏掉的。反证：把 `lifecycle_q` 里的
`old_branch` 去掉，这四条对应的断言立刻红。
"""
from django.contrib.auth.models import User
from django.db.models import Q
from django.test import TestCase
from django.utils import timezone

from .models import AccountIdentity, AccountLifecycle, Profile
from .queries import (
    deleted_q,
    expiry_disabled_q,
    lifecycle_q,
    must_change_password_q,
    not_deleted_q,
)


def _user(username, *, is_active=True):
    return User.objects.create_user(username=username, password="x", is_active=is_active)


def _drop_split_rows(user):
    AccountIdentity.objects.filter(user=user).delete()
    AccountLifecycle.objects.filter(user=user).delete()


class LifecycleQueryEquivalenceTest(TestCase):
    def setUp(self):
        now = timezone.now()

        # 1 新表有行 + 正常
        self.clean = _user("clean")
        Profile.objects.create(user=self.clean)

        # 2 新表有行 + 已注销
        self.deleted = _user("deleted", is_active=False)
        Profile.objects.create(user=self.deleted, deleted_at=now)

        # 3 新表缺行 + 正常
        self.missing_clean = _user("missing_clean")
        Profile.objects.create(user=self.missing_clean)
        _drop_split_rows(self.missing_clean)

        # 4 新表缺行 + 已注销
        self.missing_deleted = _user("missing_deleted", is_active=False)
        Profile.objects.create(user=self.missing_deleted, deleted_at=now)
        _drop_split_rows(self.missing_deleted)

        # 5 新表有行 + 超期停用
        self.expired = _user("expired", is_active=False)
        Profile.objects.create(user=self.expired, expiry_disabled_at=now)

        # 6 新表缺行 + 超期停用
        self.missing_expired = _user("missing_expired", is_active=False)
        Profile.objects.create(user=self.missing_expired, expiry_disabled_at=now)
        _drop_split_rows(self.missing_expired)

        # 7 新表有行 + 需改密
        self.mcp = _user("mcp")
        Profile.objects.create(user=self.mcp, must_change_password=True)

        # 8 新表缺行 + 需改密
        self.missing_mcp = _user("missing_mcp")
        Profile.objects.create(user=self.missing_mcp, must_change_password=True)
        _drop_split_rows(self.missing_mcp)

    def _compare(self, legacy_q, new_q):
        legacy = set(Profile.objects.filter(legacy_q).values_list("user_id", flat=True))
        new = set(Profile.objects.filter(new_q).values_list("user_id", flat=True))
        return legacy, new

    def test_not_deleted_equivalent(self):
        legacy, new = self._compare(Q(deleted_at__isnull=True), not_deleted_q())
        self.assertEqual(legacy, new)
        # 防「两边都空」的假等价
        self.assertIn(self.clean.pk, new)
        self.assertIn(self.missing_clean.pk, new)  # ← INNER JOIN 写法会漏掉这个
        self.assertNotIn(self.deleted.pk, new)
        self.assertNotIn(self.missing_deleted.pk, new)

    def test_deleted_equivalent(self):
        legacy, new = self._compare(Q(deleted_at__isnull=False), deleted_q())
        self.assertEqual(legacy, new)
        self.assertEqual(new, {self.deleted.pk, self.missing_deleted.pk})

    def test_expiry_disabled_equivalent(self):
        legacy, new = self._compare(
            Q(expiry_disabled_at__isnull=False), expiry_disabled_q(),
        )
        self.assertEqual(legacy, new)
        self.assertEqual(new, {self.expired.pk, self.missing_expired.pk})

    def test_must_change_password_equivalent(self):
        legacy, new = self._compare(
            Q(must_change_password=True), must_change_password_q(),
        )
        self.assertEqual(legacy, new)
        self.assertEqual(new, {self.mcp.pk, self.missing_mcp.pk})

    def test_lifecycle_q_rejects_bad_args(self):
        with self.assertRaises(ValueError):
            lifecycle_q("deleted_at")
        with self.assertRaises(ValueError):
            lifecycle_q("deleted_at", value=1, isnull=True)
