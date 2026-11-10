"""B4 之后「账号实名 / 生命周期字段」的查询条件构造。

## 为什么需要这一层

``Profile.objects.filter(deleted_at__isnull=True)`` 拼的是 SQL 列名，绕不过 ORM 的
property。B4 把这些字段拆到 ``AccountIdentity`` / ``AccountLifecycle`` 后，查询必须
写成联结形式：

```python
Profile.objects.filter(user__lifecycle__deleted_at__isnull=True)
```

## 历史：这里曾经有「回落旧列」分支

PR 2b / 3b1 阶段旧列还在，新表可能有缺行（PR 1 之后、2a 之前创建的用户）。
那时每个条件都是两条分支：

```python
Q(user__lifecycle__isnull=False) & Q(user__lifecycle__deleted_at__isnull=True)   # 新表有行
| Q(user__lifecycle__isnull=True) & Q(deleted_at__isnull=True)                   # 缺行回落旧列
```

PR 3b2 删掉旧列后回落分支失去意义（字段不存在），只剩新表分支。

## 缺行的用户会怎样

INNER JOIN 语义：``AccountLifecycle`` 没行的用户会被**排除**。

这是有意的——缺行属异常状态。两道保险保证它不会发生：

1. ``0035_drop_profile_legacy_columns`` 迁移在删列前补齐所有存量
2. ``Profile.save()`` → ``ensure_split_rows()`` 保证新注册用户建行

真出现了用 ``manage.py check_profile_sync`` 排查。
"""
from __future__ import annotations

from django.db.models import Q


def _split_q(relation, field, suffix):
    """``relation`` 是 ``user__lifecycle`` 或 ``user__identity_record``。

    ``suffix`` 的键有两种来源，必须区分：
    - ``lifecycle_q`` 传 ``""`` / ``"__isnull"``（已经带分隔符）
    - ``identity_q`` 传 ``"iexact"`` / ``"contains"``（裸 lookup 名，要补 ``__``）

    混用会让 ``real_name`` + ``exact`` 拼成 ``real_nameexact``——Django 报
    ``Unsupported lookup``，但只在真正执行查询时才炸，很容易漏。
    """
    q = Q()
    for sfx, val in suffix.items():
        sep = "" if sfx == "" or sfx.startswith("__") else "__"
        q &= Q(**{f"{relation}__{field}{sep}{sfx}": val})
    return q


def _suffix(value, isnull):
    if (value is None) == (isnull is None):
        raise ValueError("需要 value 或 isnull 恰好一个")
    return {"": value} if value is not None else {"__isnull": isnull}


def lifecycle_q(field, *, value=None, isnull=None):
    """生命周期字段的查询条件。

    ``field``：``deleted_at`` / ``expiry_disabled_at`` / ``registration_deadline`` /
    ``validity_notice_ack`` / ``must_change_password``。
    """
    return _split_q("user__lifecycle", field, _suffix(value, isnull))


def not_deleted_q():
    """「未注销」——等价于旧的 ``deleted_at__isnull=True``。"""
    return lifecycle_q("deleted_at", isnull=True)


def deleted_q():
    """「已注销」——等价于旧的 ``deleted_at__isnull=False``。"""
    return lifecycle_q("deleted_at", isnull=False)


def expiry_disabled_q():
    """「因超期停用」——等价于旧的 ``expiry_disabled_at__isnull=False``。"""
    return lifecycle_q("expiry_disabled_at", isnull=False)


def must_change_password_q():
    """「需强制改密」——等价于旧的 ``must_change_password=True``。"""
    return lifecycle_q("must_change_password", value=True)


def identity_q(field, **lookup):
    """实名资料字段的查询条件。

    ``field`` 只接受两边**同名且语义相同**的字段：``real_name`` / ``identity``。

    **不包括 ``card_no``** —— 它在新表叫 ``pending_card_no``，语义也从「校牌号」
    变成了「待绑定暂存」（B4 PR 3a）。混用会让「已绑定用户」的查询意外命中，
    而绑定之后暂存本该是空的。

    用法::

        Profile.objects.filter(identity_q("real_name", iexact=name))
        Profile.objects.filter(identity_q("real_name", contains=kw))
    """
    if not lookup:
        raise ValueError("identity_q 至少需要一个查询条件")
    return _split_q("user__identity_record", field, lookup)
